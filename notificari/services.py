import hashlib
import logging
from dataclasses import dataclass

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from conturi.models import Utilizator

from .models import Notificare

logger = logging.getLogger(__name__)
ROLURI_CONTABILE = {"contabil", "contabil_coordonator"}


@dataclass(frozen=True)
class DestinatarNotificare:
    id: object
    email: str
    nume: str


def _din_queryset(queryset) -> list[DestinatarNotificare]:
    return [
        DestinatarNotificare(id=rand["id"], email=rand["email"], nume=rand["nume"])
        for rand in queryset.values("id", "email", "nume")
    ]


def normalizeaza_destinatari(
    destinatari: list[DestinatarNotificare] | tuple[DestinatarNotificare, ...],
    *,
    exclude_id=None,
) -> tuple[DestinatarNotificare, ...]:
    unici = {}
    for destinatar in destinatari:
        if exclude_id is not None and str(destinatar.id) == str(exclude_id):
            continue
        unici[str(destinatar.id)] = destinatar
    return tuple(unici.values())


def cheie_deduplicare(*, tip, entitate_tip, entitate_id, eveniment_id, utilizator_id) -> str:
    continut = ":".join(
        str(valoare) for valoare in (tip, entitate_tip, entitate_id, eveniment_id, utilizator_id)
    )
    return hashlib.sha256(continut.encode()).hexdigest()


def destinatari_contabili(perioada, *, using="privileged") -> list[DestinatarNotificare]:
    baza = Utilizator.objects.using(using).filter(
        is_active=True,
        rol__in=ROLURI_CONTABILE,
    )
    if perioada.contabil_responsabil_id:
        responsabil = _din_queryset(
            baza.filter(
                pk=perioada.contabil_responsabil_id,
                cabinet_id=perioada.firma.cabinet_id,
            )
            .filter(
                Q(rol=Utilizator.Rol.CONTABIL_COORDONATOR)
                | Q(
                    rol=Utilizator.Rol.CONTABIL,
                    alocari_firme__firma_id=perioada.firma_id,
                    alocari_firme__rol_in_firma="contabil_alocat",
                )
            )
            .distinct()
        )
        if responsabil:
            return responsabil
    return _din_queryset(
        baza.filter(
            alocari_firme__firma_id=perioada.firma_id,
            alocari_firme__rol_in_firma="contabil_alocat",
        ).distinct()
    )


def destinatari_client_admin(firma_id, *, using="privileged") -> list[DestinatarNotificare]:
    return _din_queryset(
        Utilizator.objects.using(using)
        .filter(
            is_active=True,
            rol="client_admin",
            alocari_firme__firma_id=firma_id,
            alocari_firme__rol_in_firma="reprezentant_client",
        )
        .distinct()
    )


def destinatari_clienti_reminder(
    firma_id,
    *,
    using="privileged",
) -> list[DestinatarNotificare]:
    return _din_queryset(
        Utilizator.objects.using(using)
        .filter(is_active=True, alocari_firme__firma_id=firma_id)
        .filter(
            Q(
                rol=Utilizator.Rol.CLIENT_ADMIN,
                alocari_firme__rol_in_firma="reprezentant_client",
            )
            | Q(
                rol=Utilizator.Rol.CLIENT_OPERATOR,
                alocari_firme__rol_in_firma="operator_upload",
            )
        )
        .distinct()
    )


def destinatari_cu_acces_la_firma(
    firma,
    utilizator_ids,
    *,
    using="privileged",
) -> list[DestinatarNotificare]:
    """Exclude foștii membri înainte de a divulga un eveniment al firmei."""

    return _din_queryset(
        Utilizator.objects.using(using)
        .filter(pk__in=utilizator_ids, is_active=True)
        .filter(
            Q(
                rol=Utilizator.Rol.CONTABIL_COORDONATOR,
                cabinet_id=firma.cabinet_id,
            )
            | Q(
                rol=Utilizator.Rol.CONTABIL,
                cabinet_id=firma.cabinet_id,
                alocari_firme__firma_id=firma.pk,
                alocari_firme__rol_in_firma="contabil_alocat",
            )
            | Q(
                rol=Utilizator.Rol.CLIENT_ADMIN,
                alocari_firme__firma_id=firma.pk,
                alocari_firme__rol_in_firma="reprezentant_client",
            )
            | Q(
                rol=Utilizator.Rol.CLIENT_OPERATOR,
                alocari_firme__firma_id=firma.pk,
                alocari_firme__rol_in_firma="operator_upload",
            )
        )
        .distinct()
    )


def trimite_email_notificare(notificare_id) -> bool:
    """Încearcă o livrare și persistă rezultatul în același rând outbox."""
    with transaction.atomic(using="privileged"):
        notificare = (
            Notificare.objects.using("privileged")
            .select_for_update()
            .select_related("utilizator")
            .get(pk=notificare_id)
        )
        if (
            not notificare.trimite_email
            or notificare.email_trimis_la is not None
            or notificare.incercari_email >= 3
        ):
            return False

        notificare.incercari_email += 1
        try:
            send_mail(
                subject=notificare.subiect_email,
                message=(
                    f"Bună, {notificare.utilizator.nume}.\n\n{notificare.mesaj}\n\nConta Saga"
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[notificare.utilizator.email],
                fail_silently=False,
            )
        except Exception as exc:
            notificare.eroare_email = str(exc)[:2000]
            logger.exception("Emailul notificării nu a putut fi trimis")
            notificare.save(
                using="privileged",
                update_fields=["incercari_email", "eroare_email"],
            )
            return False

        notificare.email_trimis_la = timezone.now()
        notificare.eroare_email = None
        notificare.save(
            using="privileged",
            update_fields=["incercari_email", "email_trimis_la", "eroare_email"],
        )
        return True


def _livreaza(
    *,
    destinatari,
    tip,
    entitate_tip,
    entitate_id,
    mesaj,
    eveniment_id,
    cu_email,
    subiect_email,
    vizibila_in_app=True,
):
    for destinatar in destinatari:
        cheie = cheie_deduplicare(
            tip=tip,
            entitate_tip=entitate_tip,
            entitate_id=entitate_id,
            eveniment_id=eveniment_id,
            utilizator_id=destinatar.id,
        )
        notificare, _ = Notificare.objects.using("privileged").get_or_create(
            cheie_deduplicare=cheie,
            defaults={
                "utilizator_id": destinatar.id,
                "tip": tip,
                "entitate_tip": entitate_tip,
                "entitate_id": entitate_id,
                "mesaj": mesaj[:500],
                "vizibila_in_app": vizibila_in_app,
                "trimite_email": cu_email,
                "subiect_email": subiect_email if cu_email else None,
            },
        )
        if cu_email and notificare.email_trimis_la is None and notificare.incercari_email < 3:
            try:
                trimite_email_notificare(notificare.pk)
            except Exception:
                logger.exception("Livrarea notificării a eșuat neașteptat")


def programeaza_notificari(
    *,
    destinatari,
    tip,
    entitate_tip,
    entitate_id,
    mesaj,
    eveniment_id,
    exclude_id=None,
    cu_email=False,
    subiect_email="Notificare Conta Saga",
    vizibila_in_app=True,
    using="default",
):
    destinatari = normalizeaza_destinatari(destinatari, exclude_id=exclude_id)
    if not destinatari:
        return

    def callback():
        _livreaza(
            destinatari=destinatari,
            tip=tip,
            entitate_tip=entitate_tip,
            entitate_id=entitate_id,
            mesaj=mesaj,
            eveniment_id=eveniment_id,
            cu_email=cu_email,
            subiect_email=subiect_email,
            vizibila_in_app=vizibila_in_app,
        )

    transaction.on_commit(callback, using=using, robust=True)


def reincearca_emailuri_pendente(*, limit=100) -> tuple[int, int]:
    ids = list(
        Notificare.objects.using("privileged")
        .filter(
            trimite_email=True,
            email_trimis_la__isnull=True,
            incercari_email__lt=3,
        )
        .order_by("creat_la")
        .values_list("pk", flat=True)[:limit]
    )
    trimise = sum(trimite_email_notificare(notificare_id) for notificare_id in ids)
    return trimise, len(ids) - trimise


def notifica_document_trimis(*, document, actor, eveniment_id):
    perioada = document.perioada_contabila
    programeaza_notificari(
        destinatari=destinatari_contabili(perioada),
        tip=Notificare.Tip.DOCUMENT_NOU,
        entitate_tip="document",
        entitate_id=document.pk,
        mesaj=(
            f"Document nou pentru {document.firma.denumire}, "
            f"{perioada.luna:02d}/{perioada.an}: {document.tip_document.denumire}."
        ),
        eveniment_id=eveniment_id,
        exclude_id=actor.pk,
    )


def notifica_lot_documente_trimise(*, documente, actor, eveniment_id):
    if not documente:
        return
    document = documente[0]
    perioada = document.perioada_contabila
    total = len(documente)
    descriere_total = "1 document nou" if total == 1 else f"{total} documente noi"
    programeaza_notificari(
        destinatari=destinatari_contabili(perioada),
        tip=Notificare.Tip.DOCUMENT_NOU,
        entitate_tip="perioada",
        entitate_id=perioada.pk,
        mesaj=(
            f"{descriere_total} pentru {document.firma.denumire}, "
            f"{perioada.luna:02d}/{perioada.an}: {document.tip_document.denumire}."
        ),
        eveniment_id=eveniment_id,
        exclude_id=actor.pk,
    )


def notifica_clarificari_cerute(*, document, actor, eveniment_id):
    destinatari = destinatari_cu_acces_la_firma(
        document.firma,
        [document.incarcat_de_id],
    )
    destinatari.extend(destinatari_client_admin(document.firma_id))
    programeaza_notificari(
        destinatari=destinatari,
        tip=Notificare.Tip.NECESITA_CLARIFICARI,
        entitate_tip="document",
        entitate_id=document.pk,
        mesaj=f"Sunt necesare clarificări pentru {document.tip_document.denumire}.",
        eveniment_id=eveniment_id,
        exclude_id=actor.pk,
        cu_email=True,
        subiect_email="Clarificări necesare pentru un document",
    )


def notifica_raspuns_clarificare(*, document, actor, eveniment_id):
    programeaza_notificari(
        destinatari=destinatari_contabili(document.perioada_contabila),
        tip=Notificare.Tip.CLARIFICARI_REZOLVATE,
        entitate_tip="document",
        entitate_id=document.pk,
        mesaj=f"Clientul a răspuns clarificării pentru {document.tip_document.denumire}.",
        eveniment_id=eveniment_id,
        exclude_id=actor.pk,
    )


def notifica_perioada_confirmata(*, perioada, actor, eveniment_id):
    programeaza_notificari(
        destinatari=destinatari_contabili(perioada),
        tip=Notificare.Tip.PERIOADA_CONFIRMATA,
        entitate_tip="perioada",
        entitate_id=perioada.pk,
        mesaj=(
            f"Clientul a confirmat documentele pentru "
            f"{perioada.firma.denumire}, {perioada.luna:02d}/{perioada.an}."
        ),
        eveniment_id=eveniment_id,
        exclude_id=actor.pk,
        cu_email=True,
        subiect_email="Perioadă contabilă confirmată",
    )


def notifica_toate_clarificarile_rezolvate(*, perioada, actor, eveniment_id):
    programeaza_notificari(
        destinatari=destinatari_contabili(perioada),
        tip=Notificare.Tip.CLARIFICARI_REZOLVATE,
        entitate_tip="perioada",
        entitate_id=perioada.pk,
        mesaj=(
            f"Toate clarificările sunt rezolvate pentru "
            f"{perioada.firma.denumire}, {perioada.luna:02d}/{perioada.an}."
        ),
        eveniment_id=eveniment_id,
        exclude_id=actor.pk,
    )


def notifica_perioada_inchisa(*, perioada, actor, eveniment_id, using="default"):
    programeaza_notificari(
        destinatari=destinatari_client_admin(perioada.firma_id),
        tip=Notificare.Tip.PERIOADA_INCHISA,
        entitate_tip="perioada",
        entitate_id=perioada.pk,
        mesaj=(
            f"Perioada {perioada.luna:02d}/{perioada.an} pentru "
            f"{perioada.firma.denumire} a fost închisă."
        ),
        eveniment_id=eveniment_id,
        exclude_id=actor.pk,
        cu_email=True,
        subiect_email="Perioadă contabilă închisă",
        using=using,
    )


def notifica_comentariu_nou(*, document, actor, comentariu_id):
    from documente.models import Comentariu

    participanti = list(
        Comentariu.objects.filter(document_id=document.pk).values_list("utilizator_id", flat=True)
    )
    participanti.append(document.incarcat_de_id)
    destinatari = destinatari_cu_acces_la_firma(
        document.firma,
        participanti,
    )
    destinatari.extend(destinatari_contabili(document.perioada_contabila))
    programeaza_notificari(
        destinatari=destinatari,
        tip=Notificare.Tip.COMENTARIU_NOU,
        entitate_tip="document",
        entitate_id=document.pk,
        mesaj=f"Comentariu nou la {document.tip_document.denumire}.",
        eveniment_id=comentariu_id,
        exclude_id=actor.pk,
    )


def notifica_eroare_procesare_fisier(*, fisier):
    from documente.models import FisierDocument

    fisier = (
        FisierDocument.objects.using("privileged")
        .select_related("document__perioada_contabila", "document__tip_document")
        .get(pk=fisier.pk)
    )
    document = fisier.document
    destinatari = destinatari_cu_acces_la_firma(
        document.firma,
        [fisier.incarcat_de_id],
    )
    destinatari.extend(destinatari_contabili(document.perioada_contabila, using="privileged"))
    programeaza_notificari(
        destinatari=destinatari,
        tip=Notificare.Tip.EROARE_PROCESARE_FISIER,
        entitate_tip="document",
        entitate_id=document.pk,
        mesaj=f"Fișierul {fisier.nume_original or 'fără nume'} nu a putut fi procesat.",
        eveniment_id=f"{fisier.pk}:{fisier.incercari_procesare}",
        using="privileged",
    )


def notifica_export_finalizat(*, export, numar_fisiere):
    destinatar = DestinatarNotificare(
        id=export.solicitat_de_id,
        email=export.solicitat_de.email,
        nume=export.solicitat_de.nume,
    )
    perioada = export.perioada_contabila
    programeaza_notificari(
        destinatari=[destinatar],
        tip=Notificare.Tip.EXPORT_FINALIZAT,
        entitate_tip="perioada",
        entitate_id=perioada.pk,
        mesaj=(
            f"Exportul pentru {perioada.firma.denumire}, "
            f"{perioada.luna:02d}/{perioada.an}, este gata "
            f"({numar_fisiere} fișiere)."
        ),
        eveniment_id=export.pk,
        using="privileged",
    )


def trimite_email_invitatie(*, email, link_acceptare, destinatie) -> bool:
    try:
        send_mail(
            subject=f"Invitație Conta Saga — {destinatie}",
            message=(
                f"Ai fost invitat în Conta Saga pentru {destinatie}.\n\n"
                f"Acceptă invitația în maximum 7 zile:\n{link_acceptare}"
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
            fail_silently=False,
        )
        return True
    except Exception:
        logger.exception("Emailul invitației nu a putut fi trimis")
        return False
