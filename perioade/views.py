from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from conturi.models import Utilizator
from core.audit import context_audit_din_request
from core.models import IstoricStare
from documente.forms import DocumentNouForm
from documente.models import ArhivaLunara, Document, FisierInbox
from documente.services import poate_incarca_documente
from exporturi.models import Export
from exporturi.services import poate_solicita_export
from firme.models import Firma
from logistica.forms import DigitizareForm, ProgramarePredareForm
from logistica.models import PredareDocumente
from logistica.services import (
    poate_gestiona_predari,
    poate_programa_predare,
    statistici_digitizare,
)

from .forms import ActualizareCerintaForm, DeschiderePerioadaForm, RedeschiderePerioadaForm
from .models import CerintaDocumentPerioada, PerioadaContabila
from .services import (
    PerioadaDuplicata,
    TranzitieInvalida,
    actualizeaza_cerinta,
    confirma_perioada,
    deschide_perioada,
    incepe_verificarea,
    inchide_perioada,
    poate_actualiza_checklist,
    poate_deschide_perioade,
    redeschide_perioada,
)


@login_required
def perioade_firma(request, firma_id):
    firma = get_object_or_404(Firma, pk=firma_id)
    formular = DeschiderePerioadaForm(request.POST or None)
    if request.method == "POST":
        if not poate_deschide_perioade(request.user):
            raise PermissionDenied
        if formular.is_valid():
            try:
                rezultat = deschide_perioada(
                    actor=request.user,
                    firma=firma,
                    luna=formular.cleaned_data["luna"],
                    an=formular.cleaned_data["an"],
                    termen_predare=formular.cleaned_data["termen_predare"],
                    observatii=formular.cleaned_data["observatii"],
                    context=context_audit_din_request(request),
                )
            except PerioadaDuplicata:
                formular.add_error(None, "Perioada există deja pentru această firmă.")
            else:
                messages.success(
                    request,
                    f"Perioada a fost deschisă cu {rezultat.cerinte_create} cerințe.",
                )
                return redirect("perioada_detaliu", perioada_id=rezultat.perioada.pk)

    perioade = list(PerioadaContabila.objects.filter(firma=firma))
    responsabili = {
        utilizator.pk: utilizator
        for utilizator in Utilizator.objects.filter(
            pk__in=[p.contabil_responsabil_id for p in perioade if p.contabil_responsabil_id]
        )
    }
    for perioada in perioade:
        perioada.responsabil_afisat = responsabili.get(perioada.contabil_responsabil_id)
        cerinte = CerintaDocumentPerioada.objects.filter(perioada_contabila_id=perioada.pk)
        perioada.cerinte_total = cerinte.count()
        perioada.cerinte_complete = cerinte.filter(
            status__in=(
                CerintaDocumentPerioada.Status.PRIMIT,
                CerintaDocumentPerioada.Status.NU_SE_APLICA,
            )
        ).count()
        perioada.progres = (
            round(perioada.cerinte_complete * 100 / perioada.cerinte_total)
            if perioada.cerinte_total
            else 100
        )
    return render(
        request,
        "perioade/lista.html",
        {
            "firma": firma,
            "perioade": perioade,
            "formular": formular,
            "poate_deschide": poate_deschide_perioade(request.user),
        },
    )


@login_required
def perioada_detaliu(request, perioada_id):
    perioada = get_object_or_404(PerioadaContabila.objects.select_related("firma"), pk=perioada_id)
    cerinte = list(
        CerintaDocumentPerioada.objects.select_related("tip_document", "cont_financiar").filter(
            perioada_contabila=perioada
        )
    )
    istoric = IstoricStare.objects.filter(entitate_tip="perioada", entitate_id=perioada.pk)
    documente = list(
        Document.objects.select_related("tip_document", "cont_financiar")
        .filter(
            perioada_contabila=perioada,
            sters_la__isnull=True,
        )
        .annotate(
            numar_fisiere_active=Count(
                "fisiere",
                filter=Q(fisiere__activ=True, fisiere__sters_la__isnull=True),
            )
        )
    )
    documente_pe_cerinta = {}
    for document in documente:
        cheie = (document.tip_document_id, document.cont_financiar_id)
        documente_pe_cerinta.setdefault(cheie, []).append(document)
    for cerinta in cerinte:
        cerinta.documente_asociate = documente_pe_cerinta.get(
            (cerinta.tip_document_id, cerinta.cont_financiar_id), []
        )
        cerinta.documente_curente = [
            document
            for document in cerinta.documente_asociate
            if document.stare != Document.Stare.ANULAT
        ]
        cerinta.documente_active = [
            document
            for document in cerinta.documente_curente
            if document.stare not in {Document.Stare.DRAFT, Document.Stare.ANULAT}
        ]
        cerinta.numar_documente = len(cerinta.documente_curente)
        cerinta.numar_fisiere = sum(
            document.numar_fisiere_active for document in cerinta.documente_curente
        )

    statusuri_complete = {
        CerintaDocumentPerioada.Status.PRIMIT,
        CerintaDocumentPerioada.Status.NU_SE_APLICA,
    }
    cerinte_complete = sum(cerinta.status in statusuri_complete for cerinta in cerinte)
    cerinte_total = len(cerinte)
    progres = round(cerinte_complete * 100 / cerinte_total) if cerinte_total else 100
    cerinte_ramase = cerinte_total - cerinte_complete
    documente_curente = [
        document for document in documente if document.stare != Document.Stare.ANULAT
    ]
    documente_anulate = [
        document for document in documente if document.stare == Document.Stare.ANULAT
    ]
    fisiere_inbox = FisierInbox.objects.filter(
        perioada_contabila=perioada,
        status=FisierInbox.Status.DISPONIBIL,
    ).count()
    arhive_lunare = list(
        ArhivaLunara.objects.filter(perioada_contabila=perioada).order_by("-versiune")[:10]
    )
    clarificari = sum(
        document.stare == Document.Stare.NECESITA_CLARIFICARI for document in documente_curente
    )
    documente_in_coada = sum(
        document.stare
        in {
            Document.Stare.TRIMIS,
            Document.Stare.IN_VERIFICARE,
            Document.Stare.ACCEPTAT,
        }
        for document in documente_curente
    )
    poate_exporta = poate_solicita_export(request.user)
    exporturi = []
    if poate_exporta:
        exporturi = list(
            Export.objects.filter(
                perioada_contabila=perioada,
                solicitat_de_id=request.user.pk,
            )[:20]
        )
        for export in exporturi:
            export.disponibil = bool(
                export.status == Export.Status.FINALIZAT
                and export.expira_la
                and export.expira_la > timezone.now()
            )
    predari = list(PredareDocumente.objects.filter(perioada_contabila=perioada))
    poate_gestiona = poate_gestiona_predari(request.user)
    predare_digitizare_activa = None
    predare_selectata_id = request.GET.get("predare", "")
    if poate_gestiona and predare_selectata_id:
        predare_digitizare_activa = next(
            (
                predare
                for predare in predari
                if str(predare.pk) == predare_selectata_id
                and predare.digitizare_status == PredareDocumente.StatusDigitizare.IN_LUCRU
            ),
            None,
        )
    utilizatori_predari = {
        utilizator.pk: utilizator.nume
        for utilizator in Utilizator.objects.filter(
            pk__in={
                utilizator_id
                for predare in predari
                for utilizator_id in (
                    predare.creat_de_id,
                    predare.preluat_de_id,
                    predare.digitizare_inceputa_de_id,
                    predare.digitizare_finalizata_de_id,
                )
                if utilizator_id
            }
        )
    }
    for predare in predari:
        predare.creat_de_nume = utilizatori_predari.get(predare.creat_de_id)
        predare.preluat_de_nume = utilizatori_predari.get(predare.preluat_de_id)
        predare.digitizare_inceputa_de_nume = utilizatori_predari.get(
            predare.digitizare_inceputa_de_id
        )
        predare.digitizare_finalizata_de_nume = utilizatori_predari.get(
            predare.digitizare_finalizata_de_id
        )
        predare.statistici_digitizare = statistici_digitizare(predare.pk, using="default")
        predare.documente_digitizare = [
            document
            for document in documente_curente
            if document.predare_documente_id == predare.pk
        ]
        if predare.numar_documente_estimat:
            predare.progres_digitizare = min(
                100,
                round(
                    predare.statistici_digitizare.documente_digitizate
                    * 100
                    / predare.numar_documente_estimat
                ),
            )
        else:
            predare.progres_digitizare = None
        predare.poate_finaliza_digitizarea = bool(
            predare.statistici_digitizare.documente_total
            and predare.statistici_digitizare.documente_digitizate
            == predare.statistici_digitizare.documente_total
            and (
                not predare.numar_documente_estimat
                or predare.statistici_digitizare.documente_digitizate
                >= predare.numar_documente_estimat
            )
        )
    return render(
        request,
        "perioade/detaliu.html",
        {
            "perioada": perioada,
            "cerinte": cerinte,
            "istoric": istoric,
            "documente": documente_curente,
            "documente_initiale": documente_curente[:12],
            "documente_restante": documente_curente[12:],
            "documente_anulate": documente_anulate,
            "fisiere_inbox": fisiere_inbox,
            "arhive_lunare": arhive_lunare,
            "cerinte_total": cerinte_total,
            "cerinte_complete": cerinte_complete,
            "cerinte_ramase": cerinte_ramase,
            "progres": progres,
            "clarificari": clarificari,
            "documente_in_coada": documente_in_coada,
            "poate_confirma_complet": bool(
                request.user.rol == "client_admin"
                and perioada.stare == PerioadaContabila.Stare.DESCHISA
                and cerinte_ramase == 0
            ),
            "statusuri": CerintaDocumentPerioada.Status.choices,
            "poate_actualiza": poate_actualiza_checklist(request.user),
            "poate_incarca_documente": poate_incarca_documente(request.user),
            "formular_document": DocumentNouForm(perioada=perioada),
            "formular_redeschidere": RedeschiderePerioadaForm(),
            "poate_exporta": poate_exporta,
            "exporturi": exporturi,
            "predari": predari,
            "formular_predare": ProgramarePredareForm(),
            "formular_digitizare": DigitizareForm(),
            "predare_digitizare_activa": predare_digitizare_activa,
            "poate_programa_predare": poate_programa_predare(request.user),
            "poate_gestiona_predari": poate_gestiona,
        },
    )


@login_required
@require_POST
def cerinta_actualizare(request, cerinta_id):
    cerinta = get_object_or_404(CerintaDocumentPerioada, pk=cerinta_id)
    formular = ActualizareCerintaForm(request.POST)
    if formular.is_valid():
        try:
            actualizeaza_cerinta(
                cerinta_id=cerinta.pk,
                actor=request.user,
                status=formular.cleaned_data["status"],
                numar_documente_declarat=formular.cleaned_data["numar_documente_declarat"],
                observatie=formular.cleaned_data["observatie"],
                context=context_audit_din_request(request),
            )
        except TranzitieInvalida as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Cerința a fost actualizată.")
    else:
        messages.error(request, "Cerința nu a fost actualizată: verifică statusul și observația.")
    return redirect("perioada_detaliu", perioada_id=cerinta.perioada_contabila_id)


def _executa_tranzitie(request, perioada_id, functie, **kwargs):
    get_object_or_404(PerioadaContabila, pk=perioada_id)
    try:
        functie(
            perioada_id=perioada_id,
            actor=request.user,
            context=context_audit_din_request(request),
            **kwargs,
        )
    except TranzitieInvalida as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Starea perioadei a fost actualizată.")
    return redirect("perioada_detaliu", perioada_id=perioada_id)


@login_required
@require_POST
def perioada_confirmare(request, perioada_id):
    return _executa_tranzitie(request, perioada_id, confirma_perioada)


@login_required
@require_POST
def perioada_incepe(request, perioada_id):
    return _executa_tranzitie(request, perioada_id, incepe_verificarea)


@login_required
@require_POST
def perioada_inchidere(request, perioada_id):
    return _executa_tranzitie(request, perioada_id, inchide_perioada)


@login_required
@require_POST
def perioada_redeschidere(request, perioada_id):
    formular = RedeschiderePerioadaForm(request.POST)
    if not formular.is_valid():
        messages.error(request, "Motivul redeschiderii este obligatoriu.")
        return redirect("perioada_detaliu", perioada_id=perioada_id)
    return _executa_tranzitie(
        request,
        perioada_id,
        redeschide_perioada,
        motiv=formular.cleaned_data["motiv"],
    )
