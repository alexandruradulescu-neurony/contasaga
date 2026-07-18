from typing import Any

from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction

from core.audit import ContextAudit
from core.models import AuditLog

from .models import Firma, Partener


class CUIDuplicat(Exception):
    pass


class CUIDuplicatPartener(Exception):
    pass


def poate_administra_firme(utilizator) -> bool:
    return bool(
        utilizator.is_authenticated
        and utilizator.is_active
        and utilizator.rol == "admin_cabinet"
        and utilizator.cabinet_id
    )


def poate_crea_parteneri(utilizator) -> bool:
    return bool(
        utilizator.is_authenticated
        and utilizator.is_active
        and utilizator.rol in {"contabil", "contabil_coordonator"}
    )


def _verifica_administrator(utilizator) -> None:
    if not poate_administra_firme(utilizator):
        raise PermissionDenied("Doar administratorul firmei de contabilitate poate face asta.")


def _date_audit(date: dict[str, Any]) -> dict[str, Any]:
    return {
        cheie: valoare
        for cheie, valoare in date.items()
        if cheie
        in {
            "cui",
            "denumire",
            "adresa",
            "email_contact",
            "telefon_contact",
            "activa",
        }
    }


def _adauga_audit(
    *,
    firma: Firma,
    utilizator,
    actiune: str,
    context: ContextAudit,
    date_vechi: dict[str, Any] | None = None,
    date_noi: dict[str, Any] | None = None,
) -> None:
    AuditLog.objects.create(
        firma_id=firma.pk,
        utilizator_id=utilizator.pk,
        entitate_tip="firma",
        entitate_id=firma.pk,
        actiune=actiune,
        date_vechi=date_vechi,
        date_noi=date_noi,
        ip_address=context.ip_address,
        user_agent=(context.user_agent or "")[:255] or None,
    )


def creeaza_firma(*, utilizator, date: dict[str, Any], context: ContextAudit) -> Firma:
    _verifica_administrator(utilizator)
    date_curate = _date_audit(date)
    try:
        with transaction.atomic(using="default"):
            firma = Firma.objects.create(cabinet_id=utilizator.cabinet_id, **date_curate)
            _adauga_audit(
                firma=firma,
                utilizator=utilizator,
                actiune="firma_creata",
                context=context,
                date_noi=date_curate,
            )
            return firma
    except IntegrityError as exc:
        if "uq_firma_cabinet_cui" in str(exc):
            raise CUIDuplicat from exc
        raise


def actualizeaza_firma(
    *, firma_id, utilizator, date: dict[str, Any], context: ContextAudit
) -> Firma:
    _verifica_administrator(utilizator)
    date_curate = _date_audit(date)
    try:
        with transaction.atomic(using="default"):
            firma = Firma.objects.select_for_update().get(pk=firma_id)
            date_vechi = {
                camp: getattr(firma, camp)
                for camp in date_curate
                if getattr(firma, camp) != date_curate[camp]
            }
            for camp, valoare in date_curate.items():
                setattr(firma, camp, valoare)
            firma.save(update_fields=list(date_curate))
            if date_vechi:
                _adauga_audit(
                    firma=firma,
                    utilizator=utilizator,
                    actiune="firma_actualizata",
                    context=context,
                    date_vechi=date_vechi,
                    date_noi={camp: date_curate[camp] for camp in date_vechi},
                )
            return firma
    except IntegrityError as exc:
        if "uq_firma_cabinet_cui" in str(exc):
            raise CUIDuplicat from exc
        raise


def creeaza_partener(
    *, firma_id, utilizator, date: dict[str, Any], context: ContextAudit
) -> Partener:
    if not poate_crea_parteneri(utilizator):
        raise PermissionDenied("Doar contabilii pot crea parteneri în timpul verificării.")
    date_curate = {
        "tip": date["tip"],
        "cui": date.get("cui") or None,
        "denumire": date["denumire"],
        "tara": date["tara"],
    }
    try:
        with transaction.atomic(using="default"):
            firma = Firma.objects.get(pk=firma_id, activa=True)
            partener = Partener.objects.create(
                firma=firma,
                creat_de_id=utilizator.pk,
                **date_curate,
            )
            AuditLog.objects.create(
                firma_id=firma.pk,
                utilizator_id=utilizator.pk,
                entitate_tip="partener",
                entitate_id=partener.pk,
                actiune="partener_creat",
                date_noi={
                    **date_curate,
                    "id": str(partener.pk),
                },
                ip_address=context.ip_address,
                user_agent=(context.user_agent or "")[:255] or None,
            )
            return partener
    except IntegrityError as exc:
        if "uq_parteneri_firma_cui" in str(exc):
            raise CUIDuplicatPartener from exc
        raise
