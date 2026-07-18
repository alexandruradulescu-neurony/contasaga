from django.core.exceptions import PermissionDenied
from django.db import connections, transaction

from core.audit import ContextAudit
from core.models import AuditLog

from .models import ConfigurareDocumentFirma, ContFinanciar, Firma, TipDocument
from .services import poate_administra_firme


def _verifica(actor, firma: Firma) -> None:
    if not poate_administra_firme(actor) or firma.cabinet_id != actor.cabinet_id:
        raise PermissionDenied


def _audit(*, actor, firma, entitate_tip, entitate_id, actiune, date_noi, context):
    AuditLog.objects.create(
        firma_id=firma.pk,
        utilizator_id=actor.pk,
        entitate_tip=entitate_tip,
        entitate_id=entitate_id,
        actiune=actiune,
        date_noi=date_noi,
        ip_address=context.ip_address,
        user_agent=(context.user_agent or "")[:255] or None,
    )


def _regenereaza_checklisturi_deschise(firma_id) -> None:
    from perioade.models import PerioadaContabila

    ids = (
        PerioadaContabila.objects.filter(firma_id=firma_id)
        .exclude(stare="inchisa")
        .values_list("id", flat=True)
    )
    with connections["default"].cursor() as cursor:
        for perioada_id in ids:
            cursor.execute("SELECT fn_genereaza_checklist_perioada(%s)", [perioada_id])


def salveaza_configurare(
    *, actor, firma: Firma, tip_document: TipDocument, date: dict, context: ContextAudit
):
    _verifica(actor, firma)
    with transaction.atomic(using="default"):
        configurare, creat = ConfigurareDocumentFirma.objects.update_or_create(
            firma=firma,
            tip_document=tip_document,
            defaults=date,
            create_defaults={**date, "creat_de_id": actor.pk},
        )
        if configurare.activ and configurare.obligatoriu:
            _regenereaza_checklisturi_deschise(firma.pk)
        _audit(
            actor=actor,
            firma=firma,
            entitate_tip="config_document",
            entitate_id=configurare.pk,
            actiune="configurare_creata" if creat else "configurare_actualizata",
            date_noi={
                "tip_document": tip_document.cod,
                "obligatoriu": configurare.obligatoriu,
                "activ": configurare.activ,
            },
            context=context,
        )
    return configurare


def salveaza_cont_financiar(*, actor, firma: Firma, date: dict, context: ContextAudit):
    _verifica(actor, firma)
    with transaction.atomic(using="default"):
        cont = ContFinanciar.objects.create(firma=firma, **date)
        if cont.activ:
            _regenereaza_checklisturi_deschise(firma.pk)
        _audit(
            actor=actor,
            firma=firma,
            entitate_tip="cont_financiar",
            entitate_id=cont.pk,
            actiune="cont_financiar_creat",
            date_noi={"tip": cont.tip, "denumire": cont.denumire, "activ": cont.activ},
            context=context,
        )
    return cont
