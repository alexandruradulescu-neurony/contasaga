from django.core.exceptions import PermissionDenied
from django.db import transaction

from core.audit import ContextAudit
from core.models import AuditLog
from firme.models import Firma

from .models import Utilizator, UtilizatorFirma

ROLURI_INTERNE = {"admin_cabinet", "contabil_coordonator", "contabil"}


class EroareAlocare(Exception):
    pass


def poate_gestiona_alocari(utilizator) -> bool:
    return bool(
        utilizator.is_authenticated
        and utilizator.is_active
        and utilizator.rol == "admin_cabinet"
        and utilizator.cabinet_id
    )


def _verifica_tinta(*, actor, utilizator: Utilizator, firma: Firma) -> None:
    if not poate_gestiona_alocari(actor):
        raise PermissionDenied
    if utilizator.rol not in ROLURI_INTERNE or utilizator.cabinet_id != actor.cabinet_id:
        raise PermissionDenied("Utilizatorul nu este membru al firmei de contabilitate.")
    if firma.cabinet_id != actor.cabinet_id:
        raise PermissionDenied("Firma clientă aparține altei firme de contabilitate.")


def _audit(*, actor, alocare_id, firma_id, actiune, context: ContextAudit, date_noi=None):
    AuditLog.objects.using("privileged").create(
        firma_id=firma_id,
        utilizator_id=actor.pk,
        entitate_tip="alocare",
        entitate_id=alocare_id,
        actiune=actiune,
        date_noi=date_noi,
        ip_address=context.ip_address,
        user_agent=(context.user_agent or "")[:255] or None,
    )


def creeaza_alocare(*, actor, utilizator: Utilizator, firma: Firma, context: ContextAudit):
    _verifica_tinta(actor=actor, utilizator=utilizator, firma=firma)
    with transaction.atomic(using="privileged"):
        if (
            UtilizatorFirma.objects.using("privileged")
            .filter(utilizator_id=utilizator.pk, firma_id=firma.pk)
            .exists()
        ):
            raise EroareAlocare("Utilizatorul este deja alocat acestei firme.")
        alocare = UtilizatorFirma.objects.using("privileged").create(
            utilizator_id=utilizator.pk,
            firma_id=firma.pk,
            rol_in_firma="contabil_alocat",
            alocat_de_id=actor.pk,
        )
        _audit(
            actor=actor,
            alocare_id=alocare.pk,
            firma_id=firma.pk,
            actiune="alocare_creata",
            context=context,
            date_noi={"utilizator_id": str(utilizator.pk), "rol": "contabil_alocat"},
        )
    return alocare


def sterge_alocare(*, actor, alocare: UtilizatorFirma, context: ContextAudit) -> None:
    if not poate_gestiona_alocari(actor):
        raise PermissionDenied
    if alocare.rol_in_firma != "contabil_alocat" or alocare.firma.cabinet_id != actor.cabinet_id:
        raise PermissionDenied

    with transaction.atomic(using="privileged"):
        rand = (
            UtilizatorFirma.objects.using("privileged")
            .select_for_update()
            .select_related("firma", "utilizator")
            .get(pk=alocare.pk)
        )
        _verifica_tinta(actor=actor, utilizator=rand.utilizator, firma=rand.firma)

        from perioade.models import PerioadaContabila

        if (
            PerioadaContabila.objects.using("privileged")
            .filter(
                firma_id=rand.firma_id,
                contabil_responsabil_id=rand.utilizator_id,
            )
            .exclude(stare=PerioadaContabila.Stare.INCHISA)
            .exists()
        ):
            raise EroareAlocare(
                "Contabilul este responsabil pentru un dosar deschis. "
                "Închide dosarul sau schimbă responsabilul înainte de eliminarea alocării."
            )
        _audit(
            actor=actor,
            alocare_id=rand.pk,
            firma_id=rand.firma_id,
            actiune="alocare_stearsa",
            context=context,
            date_noi={"utilizator_id": str(rand.utilizator_id), "rol": rand.rol_in_firma},
        )
        rand.delete(using="privileged")
