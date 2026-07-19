from dataclasses import dataclass

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, F, Q
from django.utils import timezone

from conturi.models import Utilizator, UtilizatorFirma
from core.audit import ContextAudit
from core.models import AuditLog
from perioade.models import PerioadaContabila

from .models import PredareDocumente

ROLURI_PROGRAMARE = {
    Utilizator.Rol.CONTABIL,
    Utilizator.Rol.CONTABIL_COORDONATOR,
    Utilizator.Rol.CLIENT_ADMIN,
    Utilizator.Rol.CLIENT_OPERATOR,
}
ROLURI_GESTIONARE = {
    Utilizator.Rol.CONTABIL,
    Utilizator.Rol.CONTABIL_COORDONATOR,
}
TRANZITII_PREDARI = {
    "preia": {PredareDocumente.Status.PROGRAMATA: PredareDocumente.Status.PRELUATA},
    "receptioneaza": {PredareDocumente.Status.PRELUATA: PredareDocumente.Status.RECEPTIONATA},
    "returneaza": {PredareDocumente.Status.RECEPTIONATA: PredareDocumente.Status.RETURNATA},
}
TRANZITII_DIGITIZARE = {
    "incepe": {
        PredareDocumente.StatusDigitizare.NEDECISA: PredareDocumente.StatusDigitizare.IN_LUCRU,
        PredareDocumente.StatusDigitizare.NU_E_NECESARA: PredareDocumente.StatusDigitizare.IN_LUCRU,
    },
    "omite": {
        PredareDocumente.StatusDigitizare.NEDECISA: PredareDocumente.StatusDigitizare.NU_E_NECESARA,
        PredareDocumente.StatusDigitizare.IN_LUCRU: PredareDocumente.StatusDigitizare.NU_E_NECESARA,
    },
    "finalizeaza": {
        PredareDocumente.StatusDigitizare.IN_LUCRU: PredareDocumente.StatusDigitizare.FINALIZATA,
    },
    "redeschide": {
        PredareDocumente.StatusDigitizare.FINALIZATA: PredareDocumente.StatusDigitizare.IN_LUCRU,
    },
}


class EroareLogistica(Exception):
    pass


@dataclass(frozen=True)
class StatisticiDigitizare:
    documente_total: int
    documente_digitizate: int
    fisiere_digitizate: int


def poate_programa_predare(utilizator) -> bool:
    return bool(
        utilizator.is_authenticated and utilizator.is_active and utilizator.rol in ROLURI_PROGRAMARE
    )


def poate_gestiona_predari(utilizator) -> bool:
    return bool(
        utilizator.is_authenticated and utilizator.is_active and utilizator.rol in ROLURI_GESTIONARE
    )


def stare_urmatoare_predare(stare: str, actiune: str) -> str:
    try:
        return TRANZITII_PREDARI[actiune][stare]
    except KeyError as exc:
        raise EroareLogistica(
            f"Acțiunea {actiune} nu este permisă pentru predarea în starea {stare}."
        ) from exc


def stare_urmatoare_digitizare(stare: str, actiune: str) -> str:
    try:
        return TRANZITII_DIGITIZARE[actiune][stare]
    except KeyError as exc:
        raise EroareLogistica(
            f"Acțiunea {actiune} nu este permisă pentru digitizarea în starea {stare}."
        ) from exc


def statistici_digitizare(predare_id, *, using="privileged") -> StatisticiDigitizare:
    from documente.models import Document, FisierDocument

    documente = (
        Document.objects.using(using)
        .filter(predare_documente_id=predare_id, sters_la__isnull=True)
        .exclude(stare=Document.Stare.ANULAT)
    )
    documente_cu_fisiere_procesate = documente.annotate(
        fisiere_active=Count(
            "fisiere",
            filter=Q(fisiere__activ=True, fisiere__sters_la__isnull=True),
        ),
        fisiere_active_procesate=Count(
            "fisiere",
            filter=Q(
                fisiere__activ=True,
                fisiere__sters_la__isnull=True,
                fisiere__stare_procesare=FisierDocument.StareProcesare.PROCESAT,
            ),
        ),
    ).filter(
        fisiere_active__gt=0,
        fisiere_active=F("fisiere_active_procesate"),
    )
    return StatisticiDigitizare(
        documente_total=documente.count(),
        documente_digitizate=documente_cu_fisiere_procesate.count(),
        fisiere_digitizate=FisierDocument.objects.using(using)
        .filter(
            document__predare_documente_id=predare_id,
            document__sters_la__isnull=True,
            activ=True,
            sters_la__isnull=True,
            stare_procesare=FisierDocument.StareProcesare.PROCESAT,
        )
        .exclude(document__stare=Document.Stare.ANULAT)
        .count(),
    )


def _utilizator_cu_acces(*, actor, firma, roluri) -> Utilizator:
    try:
        utilizator = Utilizator.objects.using("privileged").get(
            pk=actor.pk,
            is_active=True,
            rol__in=roluri,
        )
    except Utilizator.DoesNotExist as exc:
        raise PermissionDenied from exc

    if utilizator.rol in ROLURI_GESTIONARE:
        if utilizator.cabinet_id != firma.cabinet_id:
            raise PermissionDenied
        if utilizator.rol == Utilizator.Rol.CONTABIL and not (
            UtilizatorFirma.objects.using("privileged")
            .filter(
                utilizator_id=utilizator.pk,
                firma_id=firma.pk,
                rol_in_firma=UtilizatorFirma.Rol.CONTABIL_ALOCAT,
            )
            .exists()
        ):
            raise PermissionDenied
        return utilizator

    rol_alocare = (
        UtilizatorFirma.Rol.REPREZENTANT_CLIENT
        if utilizator.rol == Utilizator.Rol.CLIENT_ADMIN
        else UtilizatorFirma.Rol.OPERATOR_UPLOAD
    )
    if not (
        UtilizatorFirma.objects.using("privileged")
        .filter(
            utilizator_id=utilizator.pk,
            firma_id=firma.pk,
            rol_in_firma=rol_alocare,
        )
        .exists()
    ):
        raise PermissionDenied
    return utilizator


def programeaza_predare(
    *,
    perioada_id,
    actor,
    metoda: str,
    predat_de: str,
    numar_cutii: int,
    data_programata,
    observatii: str,
    context: ContextAudit,
) -> PredareDocumente:
    if not poate_programa_predare(actor):
        raise PermissionDenied
    if metoda not in PredareDocumente.Metoda.values:
        raise EroareLogistica("Metoda de predare este invalidă.")

    with transaction.atomic(using="privileged"):
        perioada = (
            PerioadaContabila.objects.using("privileged")
            .select_for_update(of=("self",))
            .select_related("firma")
            .get(pk=perioada_id)
        )
        utilizator = _utilizator_cu_acces(
            actor=actor,
            firma=perioada.firma,
            roluri=ROLURI_PROGRAMARE,
        )
        if perioada.stare in {
            PerioadaContabila.Stare.INCHIDERE_IN_CURS,
            PerioadaContabila.Stare.INCHISA,
        }:
            raise EroareLogistica("Nu se poate programa o predare nouă pe o perioadă închisă.")

        predat_de = predat_de.strip()
        observatii = observatii.strip()
        if metoda == PredareDocumente.Metoda.EXCLUSIV_DIGITAL:
            status = PredareDocumente.Status.RECEPTIONATA
            numar_cutii = 0
            data_programata = None
            data_receptie = timezone.now()
            predat_de = predat_de or utilizator.nume
        else:
            if not predat_de:
                raise EroareLogistica("Numele persoanei care predă este obligatoriu.")
            if numar_cutii < 1:
                raise EroareLogistica("Predarea fizică trebuie să conțină cel puțin o cutie.")
            if data_programata is None:
                raise EroareLogistica("Data programată este obligatorie pentru predarea fizică.")
            status = PredareDocumente.Status.PROGRAMATA
            data_receptie = None

        predare = PredareDocumente.objects.using("privileged").create(
            firma_id=perioada.firma_id,
            perioada_contabila_id=perioada.pk,
            metoda=metoda,
            status=status,
            predat_de=predat_de,
            numar_cutii=numar_cutii,
            data_programata=data_programata,
            data_receptie=data_receptie,
            digitizare_status=(
                PredareDocumente.StatusDigitizare.NU_E_NECESARA
                if metoda == PredareDocumente.Metoda.EXCLUSIV_DIGITAL
                else PredareDocumente.StatusDigitizare.NEDECISA
            ),
            observatii=observatii or None,
            creat_de_id=utilizator.pk,
        )
        AuditLog.objects.using("privileged").create(
            firma_id=perioada.firma_id,
            utilizator_id=utilizator.pk,
            entitate_tip="predare",
            entitate_id=predare.pk,
            actiune=(
                "predare_digitala"
                if metoda == PredareDocumente.Metoda.EXCLUSIV_DIGITAL
                else "predare_programata"
            ),
            date_noi={
                "perioada_contabila_id": str(perioada.pk),
                "metoda": metoda,
                "status": status,
                "numar_cutii": numar_cutii,
            },
            ip_address=context.ip_address,
            user_agent=(context.user_agent or "")[:255] or None,
        )
        return predare


def avanseaza_predare(
    *,
    predare_id,
    actiune: str,
    actor,
    context: ContextAudit,
) -> PredareDocumente:
    if not poate_gestiona_predari(actor):
        raise PermissionDenied
    if actiune not in TRANZITII_PREDARI:
        raise EroareLogistica("Acțiunea logistică este invalidă.")

    with transaction.atomic(using="privileged"):
        predare = (
            PredareDocumente.objects.using("privileged")
            .select_for_update(of=("self",))
            .select_related("firma", "perioada_contabila")
            .get(pk=predare_id)
        )
        utilizator = _utilizator_cu_acces(
            actor=actor,
            firma=predare.firma,
            roluri=ROLURI_GESTIONARE,
        )
        if predare.metoda == PredareDocumente.Metoda.EXCLUSIV_DIGITAL:
            raise EroareLogistica("O predare exclusiv digitală nu are tranziții fizice.")

        stare_veche = predare.status
        predare.status = stare_urmatoare_predare(predare.status, actiune)
        acum = timezone.now()
        campuri = ["status"]
        if actiune == "preia":
            predare.preluat_de_id = utilizator.pk
            predare.data_preluare = acum
            campuri.extend(("preluat_de", "data_preluare"))
        elif actiune == "receptioneaza":
            predare.data_receptie = acum
            campuri.append("data_receptie")
        else:
            predare.data_returnare = acum
            campuri.append("data_returnare")
        predare.save(using="privileged", update_fields=campuri)

        AuditLog.objects.using("privileged").create(
            firma_id=predare.firma_id,
            utilizator_id=utilizator.pk,
            entitate_tip="predare",
            entitate_id=predare.pk,
            actiune=f"predare_{actiune}",
            date_vechi={"status": stare_veche},
            date_noi={"status": predare.status},
            ip_address=context.ip_address,
            user_agent=(context.user_agent or "")[:255] or None,
        )
        return predare


def _predare_pentru_digitizare(*, predare_id, actor):
    predare = (
        PredareDocumente.objects.using("privileged")
        .select_for_update(of=("self",))
        .select_related("firma", "perioada_contabila")
        .get(pk=predare_id)
    )
    utilizator = _utilizator_cu_acces(
        actor=actor,
        firma=predare.firma,
        roluri=ROLURI_GESTIONARE,
    )
    if predare.metoda == PredareDocumente.Metoda.EXCLUSIV_DIGITAL:
        raise EroareLogistica("Predarea este deja exclusiv digitală.")
    if predare.status not in {
        PredareDocumente.Status.RECEPTIONATA,
        PredareDocumente.Status.RETURNATA,
    }:
        raise EroareLogistica("Digitizarea poate fi decisă numai după recepția documentelor.")
    return predare, utilizator


def _audit_digitizare(*, predare, utilizator, actiune, stare_veche, context, extra=None):
    AuditLog.objects.using("privileged").create(
        firma_id=predare.firma_id,
        utilizator_id=utilizator.pk,
        entitate_tip="predare",
        entitate_id=predare.pk,
        actiune=f"digitizare_{actiune}",
        date_vechi={"status": stare_veche},
        date_noi={"status": predare.digitizare_status, **(extra or {})},
        ip_address=context.ip_address,
        user_agent=(context.user_agent or "")[:255] or None,
    )


def incepe_digitizarea(*, predare_id, actor, numar_documente_estimat, context):
    if not poate_gestiona_predari(actor):
        raise PermissionDenied
    if numar_documente_estimat is not None and numar_documente_estimat < 1:
        raise EroareLogistica("Estimarea trebuie să fie de cel puțin un document.")
    with transaction.atomic(using="privileged"):
        predare, utilizator = _predare_pentru_digitizare(predare_id=predare_id, actor=actor)
        if predare.perioada_contabila.stare in {
            PerioadaContabila.Stare.INCHIDERE_IN_CURS,
            PerioadaContabila.Stare.INCHISA,
        }:
            raise EroareLogistica("Redeschide dosarul lunar înainte de a începe digitizarea.")
        stare_veche = predare.digitizare_status
        predare.digitizare_status = stare_urmatoare_digitizare(stare_veche, "incepe")
        predare.numar_documente_estimat = numar_documente_estimat
        predare.digitizare_inceputa_la = timezone.now()
        predare.digitizare_inceputa_de_id = utilizator.pk
        predare.save(
            using="privileged",
            update_fields=[
                "digitizare_status",
                "numar_documente_estimat",
                "digitizare_inceputa_la",
                "digitizare_inceputa_de",
            ],
        )
        _audit_digitizare(
            predare=predare,
            utilizator=utilizator,
            actiune="inceputa",
            stare_veche=stare_veche,
            context=context,
            extra={"numar_documente_estimat": numar_documente_estimat},
        )
        return predare


def omite_digitizarea(*, predare_id, actor, context):
    if not poate_gestiona_predari(actor):
        raise PermissionDenied
    with transaction.atomic(using="privileged"):
        predare, utilizator = _predare_pentru_digitizare(predare_id=predare_id, actor=actor)
        statistici = statistici_digitizare(predare.pk)
        if statistici.documente_total:
            raise EroareLogistica(
                "Digitizarea are deja documente legate. Elimină ciornele sau finalizează fluxul."
            )
        stare_veche = predare.digitizare_status
        predare.digitizare_status = stare_urmatoare_digitizare(stare_veche, "omite")
        predare.numar_documente_estimat = None
        predare.digitizare_inceputa_la = None
        predare.digitizare_inceputa_de = None
        predare.save(
            using="privileged",
            update_fields=[
                "digitizare_status",
                "numar_documente_estimat",
                "digitizare_inceputa_la",
                "digitizare_inceputa_de",
            ],
        )
        _audit_digitizare(
            predare=predare,
            utilizator=utilizator,
            actiune="omisa",
            stare_veche=stare_veche,
            context=context,
        )
        return predare


def actualizeaza_estimarea_digitizarii(*, predare_id, actor, numar_documente_estimat, context):
    if not poate_gestiona_predari(actor):
        raise PermissionDenied
    if numar_documente_estimat is not None and numar_documente_estimat < 1:
        raise EroareLogistica("Estimarea trebuie să fie de cel puțin un document.")
    with transaction.atomic(using="privileged"):
        predare, utilizator = _predare_pentru_digitizare(predare_id=predare_id, actor=actor)
        if predare.digitizare_status != PredareDocumente.StatusDigitizare.IN_LUCRU:
            raise EroareLogistica("Estimarea poate fi modificată numai în timpul digitizării.")
        estimare_veche = predare.numar_documente_estimat
        predare.numar_documente_estimat = numar_documente_estimat
        predare.save(using="privileged", update_fields=["numar_documente_estimat"])
        _audit_digitizare(
            predare=predare,
            utilizator=utilizator,
            actiune="estimare_actualizata",
            stare_veche=predare.digitizare_status,
            context=context,
            extra={
                "estimare_veche": estimare_veche,
                "numar_documente_estimat": numar_documente_estimat,
            },
        )
        return predare


def finalizeaza_digitizarea(*, predare_id, actor, context):
    if not poate_gestiona_predari(actor):
        raise PermissionDenied
    with transaction.atomic(using="privileged"):
        predare, utilizator = _predare_pentru_digitizare(predare_id=predare_id, actor=actor)
        stare_veche = predare.digitizare_status
        stare_noua = stare_urmatoare_digitizare(stare_veche, "finalizeaza")
        statistici = statistici_digitizare(predare.pk)
        if not statistici.documente_total:
            raise EroareLogistica("Încarcă cel puțin un document înainte de finalizare.")
        if statistici.documente_digitizate != statistici.documente_total:
            raise EroareLogistica("Toate documentele legate trebuie să aibă fișiere procesate.")
        if (
            predare.numar_documente_estimat
            and statistici.documente_digitizate < predare.numar_documente_estimat
        ):
            raise EroareLogistica(
                "Numărul documentelor digitizate este mai mic decât estimarea declarată."
            )
        predare.digitizare_status = stare_noua
        predare.digitizare_finalizata_la = timezone.now()
        predare.digitizare_finalizata_de_id = utilizator.pk
        predare.save(
            using="privileged",
            update_fields=[
                "digitizare_status",
                "digitizare_finalizata_la",
                "digitizare_finalizata_de",
            ],
        )
        _audit_digitizare(
            predare=predare,
            utilizator=utilizator,
            actiune="finalizata",
            stare_veche=stare_veche,
            context=context,
            extra={
                "documente_digitizate": statistici.documente_digitizate,
                "fisiere_digitizate": statistici.fisiere_digitizate,
            },
        )
        return predare


def redeschide_digitizarea(*, predare_id, actor, context):
    if not poate_gestiona_predari(actor):
        raise PermissionDenied
    with transaction.atomic(using="privileged"):
        predare, utilizator = _predare_pentru_digitizare(predare_id=predare_id, actor=actor)
        if predare.perioada_contabila.stare in {
            PerioadaContabila.Stare.INCHIDERE_IN_CURS,
            PerioadaContabila.Stare.INCHISA,
        }:
            raise EroareLogistica("Redeschide dosarul lunar înainte de a continua digitizarea.")
        stare_veche = predare.digitizare_status
        predare.digitizare_status = stare_urmatoare_digitizare(stare_veche, "redeschide")
        predare.digitizare_finalizata_la = None
        predare.digitizare_finalizata_de = None
        predare.save(
            using="privileged",
            update_fields=[
                "digitizare_status",
                "digitizare_finalizata_la",
                "digitizare_finalizata_de",
            ],
        )
        _audit_digitizare(
            predare=predare,
            utilizator=utilizator,
            actiune="redeschisa",
            stare_veche=stare_veche,
            context=context,
        )
        return predare
