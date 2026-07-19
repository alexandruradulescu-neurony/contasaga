from dataclasses import dataclass

from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.utils import timezone

from core.audit import ContextAudit
from core.models import AuditLog, IstoricStare
from firme.models import ContFinanciar, Partener, TipDocument
from logistica.models import PredareDocumente
from notificari.services import (
    notifica_clarificari_cerute,
    notifica_comentariu_nou,
    notifica_document_trimis,
    notifica_lot_documente_trimise,
    notifica_raspuns_clarificare,
)
from perioade.models import CerintaDocumentPerioada, PerioadaContabila
from perioade.services import (
    TranzitieInvalida as TranzitiePerioadaInvalida,
)
from perioade.services import (
    marcheaza_documente_incomplete,
    rezolva_clarificari_daca_e_cazul,
)

from .models import Comentariu, Document

ROLURI_INCARCARE = {"contabil", "contabil_coordonator", "client_admin", "client_operator"}
ROLURI_CONTABILE = {"contabil", "contabil_coordonator"}
ROLURI_CLIENT = {"client_admin", "client_operator"}
STARI_DOCUMENT = {valoare for valoare, _ in Document.Stare.choices}
TRANZITII_DOCUMENT = {
    "trimite": {"draft": "trimis"},
    "preia": {"trimis": "in_verificare"},
    "accepta": {"in_verificare": "acceptat"},
    "cere_clarificari": {"in_verificare": "necesita_clarificari"},
    "raspunde_clarificarii": {"necesita_clarificari": "trimis"},
    "proceseaza": {"acceptat": "procesat"},
    "returneaza": {"acceptat": "in_verificare"},
    "anuleaza": {
        "draft": "anulat",
        "trimis": "anulat",
        "in_verificare": "anulat",
        "necesita_clarificari": "anulat",
    },
    "arhiveaza": {"procesat": "arhivat"},
}
TIPURI_CU_METADATE_OBLIGATORII = {"factura", "chitanta", "aviz_expeditie"}


class TranzitieDocumentInvalida(Exception):
    pass


class DocumentDuplicat(Exception):
    pass


@dataclass(frozen=True)
class CheieChecklist:
    firma_id: object
    perioada_id: object
    tip_document_id: object
    cont_financiar_id: object | None


def stare_urmatoare_document(stare: str, actiune: str) -> str:
    try:
        return TRANZITII_DOCUMENT[actiune][stare]
    except KeyError as exc:
        raise TranzitieDocumentInvalida(
            f"Acțiunea {actiune} nu este permisă din starea {stare}."
        ) from exc


def poate_incarca_documente(utilizator) -> bool:
    return bool(
        utilizator.is_authenticated and utilizator.is_active and utilizator.rol in ROLURI_INCARCARE
    )


def poate_verifica_documente(utilizator) -> bool:
    return bool(
        utilizator.is_authenticated and utilizator.is_active and utilizator.rol in ROLURI_CONTABILE
    )


def poate_trimite_document(utilizator, document) -> bool:
    return bool(
        utilizator.is_active
        and utilizator.rol in ROLURI_INCARCARE
        and document.incarcat_de_id == utilizator.pk
    )


def poate_anula_document(utilizator, document) -> bool:
    if not utilizator.is_active:
        return False
    if document.stare == Document.Stare.DRAFT:
        return bool(utilizator.rol in ROLURI_INCARCARE and document.incarcat_de_id == utilizator.pk)
    if document.stare == Document.Stare.IN_VERIFICARE:
        return utilizator.rol in ROLURI_CONTABILE
    if document.stare in {Document.Stare.TRIMIS, Document.Stare.NECESITA_CLARIFICARI}:
        if utilizator.rol == "client_operator":
            return document.incarcat_de_id == utilizator.pk
        return utilizator.rol in ROLURI_CONTABILE | {"client_admin"}
    return False


def poate_reclasifica_document(utilizator, document) -> bool:
    if not utilizator.is_active:
        return False
    if document.stare == Document.Stare.DRAFT:
        return bool(utilizator.rol in ROLURI_INCARCARE and document.incarcat_de_id == utilizator.pk)
    return bool(
        utilizator.rol in ROLURI_CONTABILE
        and document.stare
        in {
            Document.Stare.TRIMIS,
            Document.Stare.IN_VERIFICARE,
            Document.Stare.NECESITA_CLARIFICARI,
        }
    )


def poate_comenta_document(utilizator, document) -> bool:
    return bool(
        utilizator.is_active
        and utilizator.rol in ROLURI_INCARCARE
        and not document.sters_la
        and document.perioada_contabila.stare
        not in {
            PerioadaContabila.Stare.INCHIDERE_IN_CURS,
            PerioadaContabila.Stare.INCHISA,
        }
        and document.stare not in {Document.Stare.ANULAT, Document.Stare.ARHIVAT}
    )


def _audit(*, document, actor, actiune, context, date_vechi=None, date_noi=None):
    AuditLog.objects.create(
        firma_id=document.firma_id,
        utilizator_id=actor.pk,
        entitate_tip="document",
        entitate_id=document.pk,
        actiune=actiune,
        date_vechi=date_vechi,
        date_noi=date_noi,
        ip_address=context.ip_address,
        user_agent=(context.user_agent or "")[:255] or None,
    )


def _istoric(*, document, actor, stare_veche, stare_noua, comentariu=None):
    return IstoricStare.objects.create(
        firma_id=document.firma_id,
        entitate_tip="document",
        entitate_id=document.pk,
        stare_veche=stare_veche,
        stare_noua=stare_noua,
        utilizator_id=actor.pk,
        comentariu=comentariu,
    )


def _schimba_starea(*, document, actor, actiune, context, comentariu=None):
    stare_veche = document.stare
    stare_noua = stare_urmatoare_document(stare_veche, actiune)
    document.stare = stare_noua
    document.save(update_fields=["stare"])
    istoric = _istoric(
        document=document,
        actor=actor,
        stare_veche=stare_veche,
        stare_noua=stare_noua,
        comentariu=comentariu,
    )
    _audit(
        document=document,
        actor=actor,
        actiune=f"document_{actiune}",
        context=context,
        date_vechi={"stare": stare_veche},
        date_noi={"stare": stare_noua},
    )
    return istoric


def _cheie_document(document) -> CheieChecklist:
    return CheieChecklist(
        firma_id=document.firma_id,
        perioada_id=document.perioada_contabila_id,
        tip_document_id=document.tip_document_id,
        cont_financiar_id=document.cont_financiar_id,
    )


def _sincronizeaza_checklist(*, cheie: CheieChecklist, actor, context: ContextAudit):
    try:
        cerinta = CerintaDocumentPerioada.objects.select_for_update().get(
            firma_id=cheie.firma_id,
            perioada_contabila_id=cheie.perioada_id,
            tip_document_id=cheie.tip_document_id,
            cont_financiar_id=cheie.cont_financiar_id,
        )
    except CerintaDocumentPerioada.DoesNotExist:
        return None

    exista_documente = (
        Document.objects.filter(
            firma_id=cheie.firma_id,
            perioada_contabila_id=cheie.perioada_id,
            tip_document_id=cheie.tip_document_id,
            cont_financiar_id=cheie.cont_financiar_id,
            sters_la__isnull=True,
        )
        .exclude(stare__in=(Document.Stare.DRAFT, Document.Stare.ANULAT))
        .exists()
    )
    status_vechi = cerinta.status
    if not exista_documente:
        status_nou = CerintaDocumentPerioada.Status.LIPSA
    elif status_vechi in {
        CerintaDocumentPerioada.Status.LIPSA,
        CerintaDocumentPerioada.Status.NU_SE_APLICA,
    }:
        status_nou = CerintaDocumentPerioada.Status.PARTIAL
    else:
        status_nou = status_vechi

    if status_nou == status_vechi:
        return cerinta
    cerinta.status = status_nou
    cerinta.save(update_fields=["status"])
    AuditLog.objects.create(
        firma_id=cerinta.firma_id,
        utilizator_id=actor.pk,
        entitate_tip="cerinta",
        entitate_id=cerinta.pk,
        actiune="cerinta_sincronizata",
        date_vechi={"status": status_vechi},
        date_noi={"status": status_nou},
        ip_address=context.ip_address,
        user_agent=(context.user_agent or "")[:255] or None,
    )
    return cerinta


def _verifica_perioada_editabila(document):
    if document.perioada_contabila.stare in {
        PerioadaContabila.Stare.INCHIDERE_IN_CURS,
        PerioadaContabila.Stare.INCHISA,
    }:
        raise TranzitieDocumentInvalida(
            "Documentele nu pot fi modificate în timpul sau după închiderea perioadei."
        )
    if document.sters_la:
        raise TranzitieDocumentInvalida("Documentul a fost șters.")


def _valideaza_tip_si_cont(*, perioada, tip_document, cont_financiar):
    if not tip_document.activ:
        raise TranzitieDocumentInvalida("Tipul de document nu este activ.")
    if tip_document.necesita_cont_financiar:
        if cont_financiar is None:
            raise TranzitieDocumentInvalida("Selectează contul financiar al documentului.")
        if cont_financiar.firma_id != perioada.firma_id or not cont_financiar.activ:
            raise TranzitieDocumentInvalida("Contul financiar nu este activ în această firmă.")
        compatibile = tip_document.tipuri_cont_compatibile or []
        if cont_financiar.tip not in compatibile:
            raise TranzitieDocumentInvalida("Contul financiar nu este compatibil cu documentul.")
    elif cont_financiar is not None:
        raise TranzitieDocumentInvalida("Acest tip de document nu folosește un cont financiar.")


def creeaza_document(
    *,
    actor,
    perioada_id,
    tip_document_id,
    cont_financiar_id,
    note: str,
    context: ContextAudit,
    predare_documente_id=None,
):
    if not poate_incarca_documente(actor):
        raise PermissionDenied
    with transaction.atomic(using="default"):
        perioada = PerioadaContabila.objects.select_for_update().get(pk=perioada_id)
        if perioada.stare in {
            PerioadaContabila.Stare.INCHIDERE_IN_CURS,
            PerioadaContabila.Stare.INCHISA,
        }:
            raise TranzitieDocumentInvalida("Nu poți încărca într-o perioadă închisă.")
        tip_document = TipDocument.objects.get(pk=tip_document_id, activ=True)
        cont_financiar = None
        if cont_financiar_id:
            cont_financiar = ContFinanciar.objects.get(
                pk=cont_financiar_id, firma_id=perioada.firma_id
            )
        _valideaza_tip_si_cont(
            perioada=perioada,
            tip_document=tip_document,
            cont_financiar=cont_financiar,
        )
        predare_documente = None
        if predare_documente_id:
            try:
                predare_documente = PredareDocumente.objects.get(
                    pk=predare_documente_id,
                    firma_id=perioada.firma_id,
                    perioada_contabila_id=perioada.pk,
                    status__in=(
                        PredareDocumente.Status.RECEPTIONATA,
                        PredareDocumente.Status.RETURNATA,
                    ),
                    digitizare_status=PredareDocumente.StatusDigitizare.IN_LUCRU,
                )
            except PredareDocumente.DoesNotExist as exc:
                raise TranzitieDocumentInvalida(
                    "Predarea nu are un flux de digitizare activ pentru această perioadă."
                ) from exc
        document = Document.objects.create(
            firma_id=perioada.firma_id,
            perioada_contabila=perioada,
            tip_document=tip_document,
            cont_financiar=cont_financiar,
            predare_documente=predare_documente,
            incarcat_de_id=actor.pk,
            incarcat_dupa_confirmare=perioada.confirmata_de_client_la is not None,
            note=note.strip() or None,
        )
        _istoric(
            document=document,
            actor=actor,
            stare_veche=None,
            stare_noua=Document.Stare.DRAFT,
        )
        _audit(
            document=document,
            actor=actor,
            actiune="document_creat",
            context=context,
            date_noi={
                "stare": Document.Stare.DRAFT,
                "predare_documente_id": (str(predare_documente.pk) if predare_documente else None),
            },
        )
    return document


def trimite_document(*, document_id, actor, context: ContextAudit):
    with transaction.atomic(using="default"):
        document = (
            Document.objects.select_for_update(of=("self",))
            .select_related("perioada_contabila")
            .get(pk=document_id, sters_la__isnull=True)
        )
        _verifica_perioada_editabila(document)
        if not poate_trimite_document(actor, document):
            raise PermissionDenied
        fisiere_active = document.fisiere.filter(
            activ=True,
            sters_la__isnull=True,
        )
        if (
            not fisiere_active.exists()
            or fisiere_active.exclude(stare_procesare="procesat").exists()
        ):
            raise TranzitieDocumentInvalida(
                "Toate fișierele active trebuie procesate cu succes înainte de trimitere."
            )
        istoric = _schimba_starea(
            document=document,
            actor=actor,
            actiune="trimite",
            context=context,
        )
        _sincronizeaza_checklist(cheie=_cheie_document(document), actor=actor, context=context)
        notifica_document_trimis(
            document=document,
            actor=actor,
            eveniment_id=istoric.pk,
        )
    return document


def trimite_documente_in_lot(*, document_ids, actor, context: ContextAudit):
    document_ids = list(dict.fromkeys(document_ids))
    if not document_ids or len(document_ids) > 500:
        raise TranzitieDocumentInvalida("O serie trebuie să conțină între 1 și 500 de documente.")

    with transaction.atomic(using="default"):
        documente_gasite = list(
            Document.objects.select_for_update(of=("self",))
            .select_related("firma", "perioada_contabila", "tip_document")
            .filter(pk__in=document_ids, sters_la__isnull=True)
        )
        if len(documente_gasite) != len(document_ids):
            raise PermissionDenied
        documente_dupa_id = {str(document.pk): document for document in documente_gasite}
        documente = [documente_dupa_id[str(document_id)] for document_id in document_ids]

        clasificari = {
            (
                document.firma_id,
                document.perioada_contabila_id,
                document.tip_document_id,
                document.cont_financiar_id,
                document.predare_documente_id,
            )
            for document in documente
        }
        if len(clasificari) != 1:
            raise TranzitieDocumentInvalida(
                "Toate documentele dintr-o serie trebuie să aparțină aceleiași categorii."
            )

        for document in documente:
            _verifica_perioada_editabila(document)
            if not poate_trimite_document(actor, document):
                raise PermissionDenied
            fisiere_active = document.fisiere.filter(activ=True, sters_la__isnull=True)
            if (
                not fisiere_active.exists()
                or fisiere_active.exclude(stare_procesare="procesat").exists()
            ):
                raise TranzitieDocumentInvalida(
                    "Toate fișierele active trebuie procesate cu succes înainte de trimitere."
                )

        ultimul_eveniment = None
        for document in documente:
            ultimul_eveniment = _schimba_starea(
                document=document,
                actor=actor,
                actiune="trimite",
                context=context,
            )

        _sincronizeaza_checklist(
            cheie=_cheie_document(documente[0]),
            actor=actor,
            context=context,
        )
        notifica_lot_documente_trimise(
            documente=documente,
            actor=actor,
            eveniment_id=ultimul_eveniment.pk,
        )
    return documente


def preia_document(*, document_id, actor, context: ContextAudit):
    if not poate_verifica_documente(actor):
        raise PermissionDenied
    with transaction.atomic(using="default"):
        document = (
            Document.objects.select_for_update(of=("self",))
            .select_related("perioada_contabila")
            .get(pk=document_id, sters_la__isnull=True)
        )
        _verifica_perioada_editabila(document)
        _schimba_starea(document=document, actor=actor, actiune="preia", context=context)
    return document


def reclasifica_document(
    *,
    document_id,
    actor,
    tip_document_id,
    cont_financiar_id,
    context: ContextAudit,
):
    with transaction.atomic(using="default"):
        document = (
            Document.objects.select_for_update(of=("self",))
            .select_related("perioada_contabila")
            .get(pk=document_id, sters_la__isnull=True)
        )
        _verifica_perioada_editabila(document)
        if not poate_reclasifica_document(actor, document):
            raise PermissionDenied
        cheie_veche = _cheie_document(document)
        tip_document = TipDocument.objects.get(pk=tip_document_id, activ=True)
        cont_financiar = None
        if cont_financiar_id:
            cont_financiar = ContFinanciar.objects.get(
                pk=cont_financiar_id,
                firma_id=document.firma_id,
            )
        _valideaza_tip_si_cont(
            perioada=document.perioada_contabila,
            tip_document=tip_document,
            cont_financiar=cont_financiar,
        )
        document.tip_document = tip_document
        document.cont_financiar = cont_financiar
        document.save(update_fields=["tip_document", "cont_financiar"])
        _audit(
            document=document,
            actor=actor,
            actiune="document_reclasificat",
            context=context,
            date_vechi={
                "tip_document_id": str(cheie_veche.tip_document_id),
                "cont_financiar_id": (
                    str(cheie_veche.cont_financiar_id) if cheie_veche.cont_financiar_id else None
                ),
            },
            date_noi={
                "tip_document_id": str(document.tip_document_id),
                "cont_financiar_id": (
                    str(document.cont_financiar_id) if document.cont_financiar_id else None
                ),
            },
        )
        if document.stare != Document.Stare.DRAFT:
            _sincronizeaza_checklist(cheie=cheie_veche, actor=actor, context=context)
            _sincronizeaza_checklist(
                cheie=_cheie_document(document),
                actor=actor,
                context=context,
            )
    return document


def cere_clarificari(*, document_id, actor, mesaj: str, context: ContextAudit):
    if not poate_verifica_documente(actor):
        raise PermissionDenied
    if not mesaj.strip():
        raise TranzitieDocumentInvalida("Mesajul de clarificare este obligatoriu.")
    with transaction.atomic(using="default"):
        document = (
            Document.objects.select_for_update(of=("self",))
            .select_related("perioada_contabila")
            .get(pk=document_id, sters_la__isnull=True)
        )
        _verifica_perioada_editabila(document)
        Comentariu.objects.create(
            firma_id=document.firma_id,
            document=document,
            utilizator_id=actor.pk,
            text=mesaj.strip(),
        )
        istoric = _schimba_starea(
            document=document,
            actor=actor,
            actiune="cere_clarificari",
            context=context,
            comentariu=mesaj.strip(),
        )
        try:
            marcheaza_documente_incomplete(
                perioada_id=document.perioada_contabila_id,
                actor=actor,
                context=context,
                comentariu=mesaj.strip(),
            )
        except TranzitiePerioadaInvalida as exc:
            raise TranzitieDocumentInvalida(str(exc)) from exc
        notifica_clarificari_cerute(
            document=document,
            actor=actor,
            eveniment_id=istoric.pk,
        )
    return document


def raspunde_clarificarii(*, document_id, actor, mesaj: str, context: ContextAudit):
    if actor.rol not in ROLURI_CLIENT or not actor.is_active:
        raise PermissionDenied
    if not mesaj.strip():
        raise TranzitieDocumentInvalida("Adaugă un răspuns sau reîncarcă un fișier.")
    with transaction.atomic(using="default"):
        document = (
            Document.objects.select_for_update(of=("self",))
            .select_related("perioada_contabila")
            .get(pk=document_id, sters_la__isnull=True)
        )
        _verifica_perioada_editabila(document)
        Comentariu.objects.create(
            firma_id=document.firma_id,
            document=document,
            utilizator_id=actor.pk,
            text=mesaj.strip(),
        )
        istoric = _schimba_starea(
            document=document,
            actor=actor,
            actiune="raspunde_clarificarii",
            context=context,
            comentariu=mesaj.strip(),
        )
        rezolva_clarificari_daca_e_cazul(
            perioada_id=document.perioada_contabila_id,
            actor=actor,
            context=context,
        )
        notifica_raspuns_clarificare(
            document=document,
            actor=actor,
            eveniment_id=istoric.pk,
        )
    return document


def accepta_document(
    *,
    document_id,
    actor,
    partener_id,
    directie,
    serie,
    numar,
    data_document,
    data_scadenta,
    moneda,
    valoare_fara_tva,
    valoare_tva,
    valoare_totala,
    retentie_extinsa_pana_la,
    context: ContextAudit,
):
    if not poate_verifica_documente(actor):
        raise PermissionDenied
    try:
        with transaction.atomic(using="default"):
            document = (
                Document.objects.select_for_update(of=("self",))
                .select_related("perioada_contabila", "tip_document")
                .get(pk=document_id, sters_la__isnull=True)
            )
            _verifica_perioada_editabila(document)
            stare_urmatoare_document(document.stare, "accepta")
            partener = None
            if partener_id:
                partener = Partener.objects.get(
                    pk=partener_id,
                    firma_id=document.firma_id,
                    activ=True,
                )
            serie = serie.strip() or None
            numar = numar.strip() or None
            if document.tip_document.cod in TIPURI_CU_METADATE_OBLIGATORII and not all(
                (partener, serie, numar)
            ):
                raise TranzitieDocumentInvalida(
                    "Partenerul, seria și numărul sunt obligatorii pentru acest document."
                )
            document.partener = partener
            document.directie = directie or None
            document.serie = serie
            document.numar = numar
            document.data_document = data_document
            document.data_scadenta = data_scadenta
            document.moneda = (moneda or "RON").upper()
            document.valoare_fara_tva = valoare_fara_tva
            document.valoare_tva = valoare_tva
            document.valoare_totala = valoare_totala
            document.retentie_extinsa_pana_la = retentie_extinsa_pana_la
            document.save(
                update_fields=[
                    "partener",
                    "directie",
                    "serie",
                    "numar",
                    "data_document",
                    "data_scadenta",
                    "moneda",
                    "valoare_fara_tva",
                    "valoare_tva",
                    "valoare_totala",
                    "retentie_extinsa_pana_la",
                ]
            )
            from .extraction import EroareRevizuireExtractie, revizuieste_extractie

            try:
                revizuieste_extractie(document=document, actor=actor)
            except EroareRevizuireExtractie as exc:
                raise TranzitieDocumentInvalida(str(exc)) from exc
            _schimba_starea(
                document=document,
                actor=actor,
                actiune="accepta",
                context=context,
            )
            _sincronizeaza_checklist(
                cheie=_cheie_document(document),
                actor=actor,
                context=context,
            )
        return document
    except IntegrityError as exc:
        if "uq_doc_business" in str(exc):
            raise DocumentDuplicat from exc
        raise


def proceseaza_document(*, document_id, actor, context: ContextAudit):
    if not poate_verifica_documente(actor):
        raise PermissionDenied
    with transaction.atomic(using="default"):
        document = (
            Document.objects.select_for_update(of=("self",))
            .select_related("perioada_contabila")
            .get(pk=document_id, sters_la__isnull=True)
        )
        _verifica_perioada_editabila(document)
        _schimba_starea(
            document=document,
            actor=actor,
            actiune="proceseaza",
            context=context,
        )
    return document


def returneaza_in_verificare(*, document_id, actor, motiv: str, context: ContextAudit):
    if not poate_verifica_documente(actor):
        raise PermissionDenied
    if not motiv.strip():
        raise TranzitieDocumentInvalida("Motivul returului este obligatoriu.")
    with transaction.atomic(using="default"):
        document = (
            Document.objects.select_for_update(of=("self",))
            .select_related("perioada_contabila")
            .get(pk=document_id, sters_la__isnull=True)
        )
        _verifica_perioada_editabila(document)
        _schimba_starea(
            document=document,
            actor=actor,
            actiune="returneaza",
            context=context,
            comentariu=motiv.strip(),
        )
    return document


def anuleaza_document(*, document_id, actor, motiv: str, context: ContextAudit):
    with transaction.atomic(using="default"):
        document = (
            Document.objects.select_for_update(of=("self",))
            .select_related("perioada_contabila")
            .get(pk=document_id, sters_la__isnull=True)
        )
        _verifica_perioada_editabila(document)
        stare_urmatoare_document(document.stare, "anuleaza")
        if document.stare == Document.Stare.IN_VERIFICARE:
            if not motiv.strip():
                raise TranzitieDocumentInvalida("Motivul anulării este obligatoriu.")
        if not poate_anula_document(actor, document):
            raise PermissionDenied
        era_clarificare = document.stare == Document.Stare.NECESITA_CLARIFICARI
        _schimba_starea(
            document=document,
            actor=actor,
            actiune="anuleaza",
            context=context,
            comentariu=motiv.strip() or None,
        )
        _sincronizeaza_checklist(cheie=_cheie_document(document), actor=actor, context=context)
        if era_clarificare:
            rezolva_clarificari_daca_e_cazul(
                perioada_id=document.perioada_contabila_id,
                actor=actor,
                context=context,
            )
    return document


def sterge_ciorna(*, document_id, actor, motiv: str, context: ContextAudit):
    with transaction.atomic(using="default"):
        document = (
            Document.objects.select_for_update(of=("self",))
            .select_related("perioada_contabila")
            .get(pk=document_id, sters_la__isnull=True)
        )
        _verifica_perioada_editabila(document)
        if document.stare != Document.Stare.DRAFT or document.incarcat_de_id != actor.pk:
            raise PermissionDenied
        document.sters_la = timezone.now()
        document.sters_de_id = actor.pk
        document.motiv_stergere = motiv.strip() or None
        document.save(update_fields=["sters_la", "sters_de", "motiv_stergere"])
        _audit(
            document=document,
            actor=actor,
            actiune="document_sters",
            context=context,
            date_noi={"motiv": document.motiv_stergere},
        )
    return document


def adauga_comentariu(*, document_id, actor, text: str, context: ContextAudit):
    if actor.rol not in ROLURI_INCARCARE or not actor.is_active:
        raise PermissionDenied
    if not text.strip():
        raise TranzitieDocumentInvalida("Comentariul nu poate fi gol.")
    with transaction.atomic(using="default"):
        document = Document.objects.select_related("perioada_contabila").get(
            pk=document_id,
            sters_la__isnull=True,
        )
        _verifica_perioada_editabila(document)
        if document.stare in {Document.Stare.ANULAT, Document.Stare.ARHIVAT}:
            raise TranzitieDocumentInvalida(
                "Nu se pot adăuga comentarii unui document anulat sau arhivat."
            )
        comentariu = Comentariu.objects.create(
            firma_id=document.firma_id,
            document=document,
            utilizator_id=actor.pk,
            text=text.strip(),
        )
        _audit(
            document=document,
            actor=actor,
            actiune="comentariu_adaugat",
            context=context,
        )
        notifica_comentariu_nou(
            document=document,
            actor=actor,
            comentariu_id=comentariu.pk,
        )
    return comentariu


def arhiveaza_documente_perioada(*, perioada, actor, context: ContextAudit):
    documente = list(
        Document.objects.select_for_update(of=("self",)).filter(
            perioada_contabila=perioada,
            stare=Document.Stare.PROCESAT,
            sters_la__isnull=True,
        )
    )
    for document in documente:
        _schimba_starea(
            document=document,
            actor=actor,
            actiune="arhiveaza",
            context=context,
        )
    return len(documente)
