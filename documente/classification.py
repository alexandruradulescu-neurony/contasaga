import hashlib

import fitz
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from conturi.models import Utilizator, UtilizatorFirma
from core.audit import ContextAudit
from core.models import AuditLog, IstoricStare
from firme.models import ConfigurareDocumentFirma, ContFinanciar, Firma, TipDocument
from perioade.models import CerintaDocumentPerioada, PerioadaContabila

from .extraction import creeaza_extractie_din_analiza
from .models import (
    AnalizaFisierInbox,
    DerivareFisierInbox,
    Document,
    FisierDocument,
    FisierInbox,
    IntentieUpload,
)
from .processing import proceseaza_fisier
from .storage import EroareStorage, get_document_storage


class EroareClasificareInbox(Exception):
    pass


def _numar_pagini_sursa(*, continut: bytes, mime_type: str) -> int:
    if mime_type != "application/pdf":
        return 1
    try:
        with fitz.open(stream=continut, filetype="pdf") as document:
            if document.page_count < 1:
                raise EroareClasificareInbox("PDF-ul nu conține pagini.")
            return document.page_count
    except (fitz.FileDataError, RuntimeError, ValueError) as exc:
        raise EroareClasificareInbox("PDF-ul original nu poate fi deschis.") from exc


def _contabil_cu_acces(*, actor, firma_id) -> Utilizator:
    try:
        utilizator = Utilizator.objects.using("privileged").get(
            pk=actor.pk,
            is_active=True,
            rol__in=(Utilizator.Rol.CONTABIL, Utilizator.Rol.CONTABIL_COORDONATOR),
        )
        firma = Firma.objects.using("privileged").get(pk=firma_id, activa=True)
    except (Utilizator.DoesNotExist, Firma.DoesNotExist) as exc:
        raise PermissionDenied from exc
    if utilizator.cabinet_id != firma.cabinet_id:
        raise PermissionDenied
    if utilizator.rol == Utilizator.Rol.CONTABIL and not (
        UtilizatorFirma.objects.using("privileged")
        .filter(
            utilizator_id=utilizator.pk,
            firma_id=firma_id,
            rol_in_firma=UtilizatorFirma.Rol.CONTABIL_ALOCAT,
        )
        .exists()
    ):
        raise PermissionDenied
    return utilizator


def _valideaza_tip_si_cont(*, tip_document, cont_financiar, firma_id):
    if not tip_document.activ:
        raise EroareClasificareInbox("Tipul de document nu mai este activ.")
    configurari = ConfigurareDocumentFirma.objects.using("privileged").filter(
        firma_id=firma_id,
        activ=True,
    )
    if configurari.exists() and not configurari.filter(tip_document_id=tip_document.pk).exists():
        raise EroareClasificareInbox("Tipul de document nu este configurat pentru această firmă.")
    if tip_document.necesita_cont_financiar:
        if cont_financiar is None:
            raise EroareClasificareInbox("Selectează contul financiar al documentului.")
        if cont_financiar.firma_id != firma_id or not cont_financiar.activ:
            raise EroareClasificareInbox("Contul financiar nu este activ în această firmă.")
        compatibile = tip_document.tipuri_cont_compatibile or []
        if cont_financiar.tip not in compatibile:
            raise EroareClasificareInbox("Contul financiar nu este compatibil cu documentul.")
    elif cont_financiar is not None:
        raise EroareClasificareInbox("Acest tip de document nu folosește un cont financiar.")


def _audit(*, using, fisier, actor, actiune, context, date_noi):
    AuditLog.objects.using(using).create(
        firma_id=fisier.firma_id,
        utilizator_id=actor.pk,
        entitate_tip="fisier_inbox",
        entitate_id=fisier.pk,
        actiune=actiune,
        date_noi=date_noi,
        ip_address=context.ip_address,
        user_agent=(context.user_agent or "")[:255] or None,
    )


def _actualizeaza_checklist(*, perioada, document, actor, context):
    try:
        cerinta = (
            CerintaDocumentPerioada.objects.using("privileged")
            .select_for_update(of=("self",))
            .get(
                firma_id=document.firma_id,
                perioada_contabila_id=perioada.pk,
                tip_document_id=document.tip_document_id,
                cont_financiar_id=document.cont_financiar_id,
            )
        )
    except CerintaDocumentPerioada.DoesNotExist:
        return
    status_vechi = cerinta.status
    if status_vechi not in {
        CerintaDocumentPerioada.Status.LIPSA,
        CerintaDocumentPerioada.Status.NU_SE_APLICA,
    }:
        return
    cerinta.status = CerintaDocumentPerioada.Status.PARTIAL
    cerinta.save(using="privileged", update_fields=["status"])
    AuditLog.objects.using("privileged").create(
        firma_id=document.firma_id,
        utilizator_id=actor.pk,
        entitate_tip="cerinta",
        entitate_id=cerinta.pk,
        actiune="cerinta_sincronizata",
        date_vechi={"status": status_vechi},
        date_noi={"status": cerinta.status},
        ip_address=context.ip_address,
        user_agent=(context.user_agent or "")[:255] or None,
    )


def clasifica_fisier_inbox(
    *,
    fisier_id,
    actor,
    tip_document_id,
    cont_financiar_id,
    directie,
    observatii: str,
    context: ContextAudit,
) -> Document:
    if directie not in {valoare for valoare, _ in Document.Directie.choices}:
        raise EroareClasificareInbox("Selectează direcția documentului.")
    observatii = (observatii or "").strip()
    if len(observatii) > 2000:
        raise EroareClasificareInbox("Observațiile pot avea cel mult 2.000 de caractere.")

    fisier_vizibil = FisierInbox.objects.select_related("perioada_contabila").get(pk=fisier_id)
    if fisier_vizibil.status != FisierInbox.Status.DISPONIBIL:
        raise EroareClasificareInbox("Fișierul nu mai așteaptă clasificarea.")
    storage = get_document_storage()
    try:
        continut = storage.read_bytes(fisier_vizibil.storage_key)
    except EroareStorage as exc:
        raise EroareClasificareInbox("Originalul din inbox nu mai este disponibil.") from exc
    if hashlib.sha256(continut).hexdigest() != fisier_vizibil.checksum:
        raise EroareClasificareInbox("Originalul nu mai corespunde checksum-ului din inbox.")
    numar_pagini_sursa = _numar_pagini_sursa(
        continut=continut,
        mime_type=fisier_vizibil.mime_type,
    )

    cheie_document = None
    try:
        with transaction.atomic(using="privileged"):
            fisier = (
                FisierInbox.objects.using("privileged")
                .select_for_update(of=("self",))
                .get(pk=fisier_id)
            )
            perioada = (
                PerioadaContabila.objects.using("privileged")
                .select_for_update(of=("self",))
                .get(pk=fisier.perioada_contabila_id, firma_id=fisier.firma_id)
            )
            utilizator = _contabil_cu_acces(actor=actor, firma_id=fisier.firma_id)
            if fisier.status != FisierInbox.Status.DISPONIBIL:
                raise EroareClasificareInbox("Fișierul nu mai așteaptă clasificarea.")
            if perioada.stare in {
                PerioadaContabila.Stare.INCHIDERE_IN_CURS,
                PerioadaContabila.Stare.INCHISA,
            }:
                raise EroareClasificareInbox("Perioada contabilă este închisă.")

            tip_document = TipDocument.objects.using("privileged").get(
                pk=tip_document_id,
                activ=True,
            )
            cont_financiar = None
            if cont_financiar_id:
                cont_financiar = ContFinanciar.objects.using("privileged").get(
                    pk=cont_financiar_id,
                    firma_id=fisier.firma_id,
                    activ=True,
                )
            _valideaza_tip_si_cont(
                tip_document=tip_document,
                cont_financiar=cont_financiar,
                firma_id=fisier.firma_id,
            )
            analiza = (
                AnalizaFisierInbox.objects.using("privileged")
                .select_for_update(of=("self",))
                .get(fisier_inbox_id=fisier.pk)
            )
            if analiza.status_revizuire != AnalizaFisierInbox.StatusRevizuire.IN_ASTEPTARE:
                raise EroareClasificareInbox("Fișierul a fost deja revizuit.")

            document = Document.objects.using("privileged").create(
                firma_id=fisier.firma_id,
                perioada_contabila_id=perioada.pk,
                tip_document_id=tip_document.pk,
                cont_financiar_id=cont_financiar.pk if cont_financiar else None,
                incarcat_de_id=fisier.incarcat_de_id,
                directie=directie,
                stare=Document.Stare.IN_VERIFICARE,
                incarcat_dupa_confirmare=perioada.confirmata_de_client_la is not None,
                note=(
                    f"Clasificat din inbox: {fisier.nume_original}"
                    + (f"\n{observatii}" if observatii else "")
                ),
            )
            IstoricStare.objects.using("privileged").bulk_create(
                [
                    IstoricStare(
                        firma_id=fisier.firma_id,
                        entitate_tip="document",
                        entitate_id=document.pk,
                        stare_veche=None,
                        stare_noua=Document.Stare.DRAFT,
                        utilizator_id=utilizator.pk,
                        comentariu="Creat prin clasificarea unui original din inbox.",
                    ),
                    IstoricStare(
                        firma_id=fisier.firma_id,
                        entitate_tip="document",
                        entitate_id=document.pk,
                        stare_veche=Document.Stare.DRAFT,
                        stare_noua=Document.Stare.TRIMIS,
                        utilizator_id=utilizator.pk,
                    ),
                    IstoricStare(
                        firma_id=fisier.firma_id,
                        entitate_tip="document",
                        entitate_id=document.pk,
                        stare_veche=Document.Stare.TRIMIS,
                        stare_noua=Document.Stare.IN_VERIFICARE,
                        utilizator_id=utilizator.pk,
                    ),
                ]
            )
            intentie = IntentieUpload.objects.using("privileged").create(
                firma_id=fisier.firma_id,
                document_id=document.pk,
                utilizator_id=fisier.incarcat_de_id,
                nume_original=fisier.nume_original,
            )
            cheie_document = intentie.storage_key
            storage.put_bytes(cheie_document, continut, fisier.mime_type)
            fisier_document = FisierDocument.objects.using("privileged").create(
                document_id=document.pk,
                firma_id=fisier.firma_id,
                upload_intentie_id=intentie.pk,
                storage_key=intentie.storage_key,
                nume_original=fisier.nume_original,
                mime_type=fisier.mime_type,
                dimensiune_bytes=fisier.dimensiune_bytes,
                checksum=fisier.checksum,
                numar_pagini=numar_pagini_sursa,
                ordine=1,
                versiune=1,
                incarcat_de_id=fisier.incarcat_de_id,
                activ=True,
            )
            DerivareFisierInbox.objects.using("privileged").create(
                analiza_id=analiza.pk,
                fisier_inbox_id=fisier.pk,
                fisier_document_id=fisier_document.pk,
                document_id=document.pk,
                firma_id=fisier.firma_id,
                perioada_contabila_id=perioada.pk,
                pagina_start=1,
                pagina_sfarsit=numar_pagini_sursa,
                metoda=DerivareFisierInbox.Metoda.COPIE_INTEGRALA,
                checksum_sursa=fisier.checksum,
                checksum_derivat=fisier.checksum,
                creat_de_id=utilizator.pk,
            )
            creeaza_extractie_din_analiza(
                analiza=analiza,
                document=document,
                fisier_document=fisier_document,
                campuri=analiza.campuri_extrase,
                avertismente=analiza.avertismente_extragere,
                incredere=analiza.incredere,
            )
            intentie.folosita_la = timezone.now()
            intentie.save(using="privileged", update_fields=["folosita_la"])

            sugestie_confirmata = bool(
                analiza.status == AnalizaFisierInbox.Status.FINALIZATA
                and analiza.tip_document_sugerat_id == tip_document.pk
                and analiza.cont_financiar_sugerat_id
                == (cont_financiar.pk if cont_financiar else None)
                and analiza.directie_sugerata == directie
            )
            analiza.status_revizuire = (
                AnalizaFisierInbox.StatusRevizuire.CONFIRMATA
                if sugestie_confirmata
                else AnalizaFisierInbox.StatusRevizuire.CORECTATA
            )
            analiza.revizuita_de_id = utilizator.pk
            analiza.revizuita_la = timezone.now()
            analiza.tip_document_final_id = tip_document.pk
            analiza.cont_financiar_final_id = cont_financiar.pk if cont_financiar else None
            analiza.directie_finala = directie
            analiza.document_id = document.pk
            analiza.observatii_revizuire = observatii or None
            analiza.procesare_inceputa_la = None
            if analiza.status == AnalizaFisierInbox.Status.IN_LUCRU:
                analiza.status = AnalizaFisierInbox.Status.EROARE
                analiza.eroare = "Analiza a fost oprită deoarece contabilul a clasificat fișierul."
            analiza.save(
                using="privileged",
                update_fields=[
                    "status",
                    "status_revizuire",
                    "revizuita_de",
                    "revizuita_la",
                    "tip_document_final",
                    "cont_financiar_final",
                    "directie_finala",
                    "document",
                    "observatii_revizuire",
                    "procesare_inceputa_la",
                    "eroare",
                ],
            )
            fisier.status = FisierInbox.Status.CLASIFICAT
            fisier.save(using="privileged", update_fields=["status"])
            _actualizeaza_checklist(
                perioada=perioada,
                document=document,
                actor=utilizator,
                context=context,
            )
            _audit(
                using="privileged",
                fisier=fisier,
                actor=utilizator,
                actiune="fisier_inbox_clasificat",
                context=context,
                date_noi={
                    "analiza_id": str(analiza.pk),
                    "document_id": str(document.pk),
                    "tip_document_id": str(tip_document.pk),
                    "cont_financiar_id": str(cont_financiar.pk) if cont_financiar else None,
                    "directie": directie,
                    "revizuire": analiza.status_revizuire,
                },
            )
    except Exception:
        if cheie_document:
            storage.delete(cheie_document)
        raise

    proceseaza_fisier(fisier_document.pk, reincearca=True)
    return document


def ignora_fisier_inbox(*, fisier_id, actor, motiv: str, context: ContextAudit) -> FisierInbox:
    motiv = (motiv or "").strip()
    if not motiv:
        raise EroareClasificareInbox("Motivul ignorării este obligatoriu.")
    if len(motiv) > 2000:
        raise EroareClasificareInbox("Motivul poate avea cel mult 2.000 de caractere.")
    FisierInbox.objects.get(pk=fisier_id, status=FisierInbox.Status.DISPONIBIL)
    with transaction.atomic(using="privileged"):
        fisier = (
            FisierInbox.objects.using("privileged")
            .select_for_update(of=("self",))
            .get(pk=fisier_id)
        )
        utilizator = _contabil_cu_acces(actor=actor, firma_id=fisier.firma_id)
        if fisier.status != FisierInbox.Status.DISPONIBIL:
            raise EroareClasificareInbox("Fișierul nu mai așteaptă clasificarea.")
        perioada = (
            PerioadaContabila.objects.using("privileged")
            .select_for_update(of=("self",))
            .get(pk=fisier.perioada_contabila_id, firma_id=fisier.firma_id)
        )
        if perioada.stare in {
            PerioadaContabila.Stare.INCHIDERE_IN_CURS,
            PerioadaContabila.Stare.INCHISA,
        }:
            raise EroareClasificareInbox("Perioada contabilă este închisă.")
        analiza = (
            AnalizaFisierInbox.objects.using("privileged")
            .select_for_update(of=("self",))
            .get(fisier_inbox_id=fisier.pk)
        )
        if analiza.status_revizuire != AnalizaFisierInbox.StatusRevizuire.IN_ASTEPTARE:
            raise EroareClasificareInbox("Fișierul a fost deja revizuit.")
        analiza.status_revizuire = AnalizaFisierInbox.StatusRevizuire.IGNORATA
        analiza.revizuita_de_id = utilizator.pk
        analiza.revizuita_la = timezone.now()
        analiza.observatii_revizuire = motiv
        analiza.procesare_inceputa_la = None
        if analiza.status == AnalizaFisierInbox.Status.IN_LUCRU:
            analiza.status = AnalizaFisierInbox.Status.EROARE
            analiza.eroare = "Analiza a fost oprită deoarece fișierul a fost ignorat."
        analiza.save(
            using="privileged",
            update_fields=[
                "status",
                "status_revizuire",
                "revizuita_de",
                "revizuita_la",
                "observatii_revizuire",
                "procesare_inceputa_la",
                "eroare",
            ],
        )
        fisier.status = FisierInbox.Status.IGNORAT
        fisier.save(using="privileged", update_fields=["status"])
        _audit(
            using="privileged",
            fisier=fisier,
            actor=utilizator,
            actiune="fisier_inbox_ignorat",
            context=context,
            date_noi={"analiza_id": str(analiza.pk), "motiv": motiv},
        )
    return fisier
