from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone

from documente.models import Document
from firme.models import Firma, FirmaContabilitate
from perioade.models import CerintaDocumentPerioada, PerioadaContabila

from .readiness import stare_readiness


def home(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    return redirect("login")


@login_required
def dashboard(request):
    firme = list(Firma.objects.order_by("denumire"))
    perioade_pe_firma = {}
    for perioada in PerioadaContabila.objects.filter(
        firma_id__in=[firma.pk for firma in firme]
    ).order_by("-an", "-luna"):
        perioade_pe_firma.setdefault(perioada.firma_id, []).append(perioada)

    astazi = timezone.localdate()
    luna_curenta = (astazi.year, astazi.month)
    for firma in firme:
        perioade = perioade_pe_firma.get(firma.pk, [])
        perioade_pana_azi = [
            perioada for perioada in perioade if (perioada.an, perioada.luna) <= luna_curenta
        ]
        firma.perioada_curenta = next(
            (
                perioada
                for perioada in perioade_pana_azi
                if perioada.stare != PerioadaContabila.Stare.INCHISA
            ),
            perioade_pana_azi[0] if perioade_pana_azi else None,
        )
        if firma.perioada_curenta is None and perioade:
            # O firmă nouă poate avea doar o perioadă viitoare configurată.
            firma.perioada_curenta = perioade[-1]
        firma.progres = 0
        firma.cerinte_complete = 0
        firma.cerinte_total = 0
        firma.documente_de_lucrat = 0
        if firma.perioada_curenta:
            cerinte = CerintaDocumentPerioada.objects.filter(
                perioada_contabila_id=firma.perioada_curenta.pk
            )
            firma.cerinte_total = cerinte.count()
            firma.cerinte_complete = cerinte.filter(
                status__in=(
                    CerintaDocumentPerioada.Status.PRIMIT,
                    CerintaDocumentPerioada.Status.NU_SE_APLICA,
                )
            ).count()
            if firma.cerinte_total:
                firma.progres = round(firma.cerinte_complete * 100 / firma.cerinte_total)
            firma.documente_de_lucrat = Document.objects.filter(
                perioada_contabila_id=firma.perioada_curenta.pk,
                stare__in=(
                    Document.Stare.TRIMIS,
                    Document.Stare.IN_VERIFICARE,
                    Document.Stare.NECESITA_CLARIFICARI,
                    Document.Stare.ACCEPTAT,
                ),
                sters_la__isnull=True,
            ).count()

    este_contabil = request.user.rol in {"contabil", "contabil_coordonator"}
    este_client = request.user.rol in {"client_admin", "client_operator"}
    documente_de_verificat = 0
    clarificari_de_rezolvat = 0
    if este_contabil:
        documente_de_verificat = Document.objects.filter(
            stare__in=(Document.Stare.TRIMIS, Document.Stare.IN_VERIFICARE),
            sters_la__isnull=True,
        ).count()
    elif este_client:
        clarificari_de_rezolvat = Document.objects.filter(
            stare=Document.Stare.NECESITA_CLARIFICARI,
            sters_la__isnull=True,
        ).count()

    firma_contabilitate = None
    if request.user.cabinet_id:
        firma_contabilitate = FirmaContabilitate.objects.filter(pk=request.user.cabinet_id).first()
    return render(
        request,
        "dashboard.html",
        {
            "firme": firme,
            "firma_contabilitate": firma_contabilitate,
            "este_contabil": este_contabil,
            "este_client": este_client,
            "documente_de_verificat": documente_de_verificat,
            "clarificari_de_rezolvat": clarificari_de_rezolvat,
            "dosare_active": sum(
                1
                for firma in firme
                if firma.perioada_curenta and firma.perioada_curenta.stare != "inchisa"
            ),
        },
    )


def health_live(request):
    return JsonResponse({"status": "ok"})


def health_ready(request):
    componente = stare_readiness()
    pregatit = all(componente.values())
    return JsonResponse(
        {
            "status": "ok" if pregatit else "unavailable",
            "checks": componente,
        },
        status=200 if pregatit else 503,
    )


def health(request):
    return health_ready(request)
