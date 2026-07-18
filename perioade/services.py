from dataclasses import dataclass

from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, connections, transaction
from django.utils import timezone

from core.audit import ContextAudit
from core.models import AuditLog, IstoricStare
from firme.models import Firma
from notificari.services import (
    notifica_perioada_confirmata,
    notifica_perioada_inchisa,
    notifica_toate_clarificarile_rezolvate,
)

from .models import CerintaDocumentPerioada, PerioadaContabila

ROLURI_CONTABILE = {"contabil", "contabil_coordonator"}
ROLURI_CHECKLIST = ROLURI_CONTABILE | {"client_admin"}
ROLURI_CLARIFICARI = ROLURI_CHECKLIST | {"client_operator"}
TRANZITII_PERIOADA = {
    "confirma": {"deschisa": "gata_pentru_verificare"},
    "incepe_verificarea": {"gata_pentru_verificare": "in_lucru"},
    "cere_clarificari": {
        "gata_pentru_verificare": "documente_incomplete",
        "in_lucru": "documente_incomplete",
    },
    "clarificari_rezolvate": {"documente_incomplete": "in_lucru"},
    "inchide": {"in_lucru": "inchisa"},
    "redeschide": {"inchisa": "in_lucru"},
}


class TranzitieInvalida(Exception):
    pass


class PerioadaDuplicata(Exception):
    pass


@dataclass(frozen=True)
class RezultatDeschidere:
    perioada: PerioadaContabila
    cerinte_create: int


def stare_urmatoare(stare: str, actiune: str) -> str:
    try:
        return TRANZITII_PERIOADA[actiune][stare]
    except KeyError as exc:
        raise TranzitieInvalida(f"Acțiunea {actiune} nu este permisă din starea {stare}.") from exc


def poate_deschide_perioade(utilizator) -> bool:
    return bool(
        utilizator.is_authenticated and utilizator.is_active and utilizator.rol in ROLURI_CONTABILE
    )


def poate_actualiza_checklist(utilizator) -> bool:
    return bool(
        utilizator.is_authenticated and utilizator.is_active and utilizator.rol in ROLURI_CHECKLIST
    )


def poate_confirma_perioada(utilizator) -> bool:
    return bool(
        utilizator.is_authenticated and utilizator.is_active and utilizator.rol == "client_admin"
    )


def poate_procesa_perioada(utilizator) -> bool:
    return bool(
        utilizator.is_authenticated and utilizator.is_active and utilizator.rol in ROLURI_CONTABILE
    )


def poate_redeschide_perioada(utilizator) -> bool:
    return bool(
        utilizator.is_authenticated
        and utilizator.is_active
        and utilizator.rol in {"admin_cabinet", "contabil_coordonator"}
    )


def _audit(*, perioada, actor, actiune, context, date_noi=None):
    AuditLog.objects.create(
        firma_id=perioada.firma_id,
        utilizator_id=actor.pk,
        entitate_tip="perioada",
        entitate_id=perioada.pk,
        actiune=actiune,
        date_noi=date_noi,
        ip_address=context.ip_address,
        user_agent=(context.user_agent or "")[:255] or None,
    )


def _istoric(*, perioada, actor, stare_veche, stare_noua, comentariu=None):
    return IstoricStare.objects.create(
        firma_id=perioada.firma_id,
        entitate_tip="perioada",
        entitate_id=perioada.pk,
        stare_veche=stare_veche,
        stare_noua=stare_noua,
        utilizator_id=actor.pk,
        comentariu=comentariu,
    )


def deschide_perioada(
    *,
    actor,
    firma: Firma,
    luna: int,
    an: int,
    termen_predare,
    observatii: str,
    context: ContextAudit,
) -> RezultatDeschidere:
    if not poate_deschide_perioade(actor):
        raise PermissionDenied
    try:
        with transaction.atomic(using="default"):
            perioada = PerioadaContabila.objects.create(
                firma=firma,
                luna=luna,
                an=an,
                termen_predare=termen_predare,
                contabil_responsabil_id=actor.pk,
                observatii=observatii.strip() or None,
            )
            with connections["default"].cursor() as cursor:
                cursor.execute("SELECT fn_genereaza_checklist_perioada(%s)", [perioada.pk])
                cerinte_create = cursor.fetchone()[0]
            _istoric(
                perioada=perioada,
                actor=actor,
                stare_veche=None,
                stare_noua="deschisa",
            )
            _audit(
                perioada=perioada,
                actor=actor,
                actiune="perioada_deschisa",
                context=context,
                date_noi={"luna": luna, "an": an, "cerinte": cerinte_create},
            )
            return RezultatDeschidere(perioada=perioada, cerinte_create=cerinte_create)
    except IntegrityError as exc:
        if "uq_perioada_firma_luna_an" in str(exc):
            raise PerioadaDuplicata from exc
        raise


def actualizeaza_cerinta(
    *,
    cerinta_id,
    actor,
    status: str,
    numar_documente_declarat,
    observatie: str,
    context: ContextAudit,
):
    if not poate_actualiza_checklist(actor):
        raise PermissionDenied
    with transaction.atomic(using="default"):
        cerinta = (
            CerintaDocumentPerioada.objects.select_for_update()
            .select_related("perioada_contabila")
            .get(pk=cerinta_id)
        )
        if cerinta.perioada_contabila.stare == "inchisa":
            raise TranzitieInvalida("Checklist-ul unei perioade închise este imuabil.")
        stare_veche = cerinta.status
        cerinta.status = status
        cerinta.numar_documente_declarat = numar_documente_declarat
        camp_observatie = (
            "observatii_client"
            if actor.rol in {"client_admin", "client_operator"}
            else "observatii_contabil"
        )
        setattr(cerinta, camp_observatie, observatie.strip() or None)
        cerinta.save(update_fields=["status", "numar_documente_declarat", camp_observatie])
        AuditLog.objects.create(
            firma_id=cerinta.firma_id,
            utilizator_id=actor.pk,
            entitate_tip="cerinta",
            entitate_id=cerinta.pk,
            actiune="cerinta_actualizata",
            date_vechi={"status": stare_veche},
            date_noi={"status": status},
            ip_address=context.ip_address,
            user_agent=(context.user_agent or "")[:255] or None,
        )
    return cerinta


def _schimba_starea(*, perioada, actor, stare_noua, actiune, context, comentariu=None):
    stare_veche = perioada.stare
    perioada.stare = stare_noua
    perioada.save(update_fields=["stare"])
    istoric = _istoric(
        perioada=perioada,
        actor=actor,
        stare_veche=stare_veche,
        stare_noua=stare_noua,
        comentariu=comentariu,
    )
    _audit(
        perioada=perioada,
        actor=actor,
        actiune=actiune,
        context=context,
        date_noi={"stare": stare_noua},
    )
    return istoric


def confirma_perioada(*, perioada_id, actor, context: ContextAudit):
    if not poate_confirma_perioada(actor):
        raise PermissionDenied
    with transaction.atomic(using="default"):
        perioada = PerioadaContabila.objects.select_for_update().get(pk=perioada_id)
        stare_noua = stare_urmatoare(perioada.stare, "confirma")
        if perioada.cerinte.exclude(status__in=("primit", "nu_se_aplica")).exists():
            raise TranzitieInvalida("Toate cerințele trebuie să fie primite sau neaplicabile.")
        perioada.confirmata_de_client_la = timezone.now()
        perioada.save(update_fields=["confirmata_de_client_la"])
        istoric = _schimba_starea(
            perioada=perioada,
            actor=actor,
            stare_noua=stare_noua,
            actiune="perioada_confirmata",
            context=context,
        )
        notifica_perioada_confirmata(
            perioada=perioada,
            actor=actor,
            eveniment_id=istoric.pk,
        )
    return perioada


def incepe_verificarea(*, perioada_id, actor, context: ContextAudit):
    if not poate_procesa_perioada(actor):
        raise PermissionDenied
    with transaction.atomic(using="default"):
        perioada = PerioadaContabila.objects.select_for_update().get(pk=perioada_id)
        stare_noua = stare_urmatoare(perioada.stare, "incepe_verificarea")
        _schimba_starea(
            perioada=perioada,
            actor=actor,
            stare_noua=stare_noua,
            actiune="verificare_inceputa",
            context=context,
        )
    return perioada


def marcheaza_documente_incomplete(*, perioada_id, actor, context: ContextAudit, comentariu: str):
    if not poate_procesa_perioada(actor):
        raise PermissionDenied
    with transaction.atomic(using="default"):
        perioada = PerioadaContabila.objects.select_for_update().get(pk=perioada_id)
        if perioada.stare == "inchisa":
            raise TranzitieInvalida("O perioadă închisă nu poate primi clarificări.")
        if perioada.stare not in {"gata_pentru_verificare", "in_lucru"}:
            return perioada
        _schimba_starea(
            perioada=perioada,
            actor=actor,
            stare_noua=stare_urmatoare(perioada.stare, "cere_clarificari"),
            actiune="documente_incomplete",
            context=context,
            comentariu=comentariu,
        )
    return perioada


def rezolva_clarificari_daca_e_cazul(*, perioada_id, actor, context: ContextAudit):
    if actor.rol not in ROLURI_CLARIFICARI or not actor.is_active:
        raise PermissionDenied
    with transaction.atomic(using="default"):
        perioada = PerioadaContabila.objects.select_for_update().get(pk=perioada_id)
        if perioada.stare != "documente_incomplete":
            return perioada
        with connections["default"].cursor() as cursor:
            cursor.execute(
                """
                SELECT count(*) FROM documente
                WHERE perioada_contabila_id = %s
                  AND stare = 'necesita_clarificari'
                  AND sters_la IS NULL
                """,
                [perioada.pk],
            )
            if cursor.fetchone()[0]:
                return perioada
        istoric = _schimba_starea(
            perioada=perioada,
            actor=actor,
            stare_noua=stare_urmatoare(perioada.stare, "clarificari_rezolvate"),
            actiune="clarificari_rezolvate",
            context=context,
        )
        notifica_toate_clarificarile_rezolvate(
            perioada=perioada,
            actor=actor,
            eveniment_id=istoric.pk,
        )
    return perioada


def inchide_perioada(*, perioada_id, actor, context: ContextAudit):
    if not poate_procesa_perioada(actor):
        raise PermissionDenied
    with transaction.atomic(using="default"):
        perioada = PerioadaContabila.objects.select_for_update().get(pk=perioada_id)
        stare_noua = stare_urmatoare(perioada.stare, "inchide")
        if perioada.cerinte.exclude(status__in=("primit", "nu_se_aplica")).exists():
            raise TranzitieInvalida("Checklist-ul nu este complet.")
        from logistica.models import PredareDocumente

        if PredareDocumente.objects.filter(
            perioada_contabila_id=perioada.pk,
            digitizare_status=PredareDocumente.StatusDigitizare.IN_LUCRU,
        ).exists():
            raise TranzitieInvalida(
                "Finalizează sau abandonează digitizările în lucru înainte de închiderea dosarului."
            )
        with connections["default"].cursor() as cursor:
            cursor.execute(
                """
                SELECT count(*) FROM documente
                WHERE perioada_contabila_id = %s
                  AND stare NOT IN ('procesat', 'anulat', 'arhivat')
                  AND sters_la IS NULL
                """,
                [perioada.pk],
            )
            if cursor.fetchone()[0]:
                raise TranzitieInvalida("Există documente care nu au fost procesate sau anulate.")
        from documente.services import arhiveaza_documente_perioada

        arhiveaza_documente_perioada(perioada=perioada, actor=actor, context=context)
        perioada.inchisa_la = timezone.now()
        perioada.inchisa_de_id = actor.pk
        perioada.save(update_fields=["inchisa_la", "inchisa_de"])
        istoric = _schimba_starea(
            perioada=perioada,
            actor=actor,
            stare_noua=stare_noua,
            actiune="perioada_inchisa",
            context=context,
        )
        notifica_perioada_inchisa(
            perioada=perioada,
            actor=actor,
            eveniment_id=istoric.pk,
        )
    return perioada


def redeschide_perioada(*, perioada_id, actor, motiv: str, context: ContextAudit):
    if not poate_redeschide_perioada(actor):
        raise PermissionDenied
    if not motiv.strip():
        raise TranzitieInvalida("Motivul redeschiderii este obligatoriu.")
    with transaction.atomic(using="default"):
        perioada = PerioadaContabila.objects.select_for_update().get(pk=perioada_id)
        stare_noua = stare_urmatoare(perioada.stare, "redeschide")
        perioada.inchisa_la = None
        perioada.inchisa_de_id = None
        perioada.save(update_fields=["inchisa_la", "inchisa_de"])
        _schimba_starea(
            perioada=perioada,
            actor=actor,
            stare_noua=stare_noua,
            actiune="perioada_redeschisa",
            context=context,
            comentariu=motiv.strip(),
        )
    return perioada
