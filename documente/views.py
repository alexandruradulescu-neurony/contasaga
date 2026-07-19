from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Case, Count, IntegerField, Value, When
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_POST

from conturi.models import Utilizator
from core.audit import context_audit_din_request
from core.models import IstoricStare
from firme.forms import PartenerForm
from firme.models import Firma
from firme.services import CUIDuplicatPartener, creeaza_partener
from perioade.models import PerioadaContabila

from .access import (
    EroareAccesFisier,
    continut_local_semnat,
    url_acces_fisier,
)
from .extraction import sugestii_pentru_document
from .forms import (
    AcceptareDocumentForm,
    ComentariuForm,
    DocumentNouForm,
    MesajForm,
    MotivForm,
    ReclasificareDocumentForm,
)
from .models import Document, FisierDocument, IntentieUpload
from .services import (
    DocumentDuplicat,
    TranzitieDocumentInvalida,
    accepta_document,
    adauga_comentariu,
    anuleaza_document,
    cere_clarificari,
    creeaza_document,
    poate_anula_document,
    poate_comenta_document,
    poate_reclasifica_document,
    poate_verifica_documente,
    preia_document,
    proceseaza_document,
    raspunde_clarificarii,
    reclasifica_document,
    returneaza_in_verificare,
    sterge_ciorna,
    trimite_document,
    trimite_documente_in_lot,
)
from .upload import (
    EroareUpload,
    finalizeaza_upload,
    initiaza_upload,
    poate_atasa_fisiere,
    primeste_upload_local,
    sterge_fisier,
)


@login_required
@require_POST
def document_nou(request, perioada_id):
    perioada = get_object_or_404(
        PerioadaContabila.objects.select_related("firma"),
        pk=perioada_id,
    )
    formular = DocumentNouForm(request.POST, perioada=perioada)
    if not formular.is_valid():
        messages.error(request, "Documentul nu a fost creat. Verifică tipul și contul financiar.")
        return redirect("perioada_detaliu", perioada_id=perioada.pk)
    try:
        document = creeaza_document(
            actor=request.user,
            perioada_id=perioada.pk,
            tip_document_id=formular.cleaned_data["tip_document"].pk,
            cont_financiar_id=(
                formular.cleaned_data["cont_financiar"].pk
                if formular.cleaned_data["cont_financiar"]
                else None
            ),
            note=formular.cleaned_data["note"],
            context=context_audit_din_request(request),
            predare_documente_id=request.POST.get("predare_documente") or None,
        )
    except TranzitieDocumentInvalida as exc:
        messages.error(request, str(exc))
        return redirect("perioada_detaliu", perioada_id=perioada.pk)
    messages.success(
        request,
        "Documentul este pregătit. Adaugă fișierele și trimite-l contabilului.",
    )
    return redirect("document_detaliu", document_id=document.pk)


@login_required
@require_POST
def document_copie_upload(request, document_id):
    """Create another draft with the same monthly checklist classification."""
    document_sursa = get_object_or_404(
        Document.objects.select_related("perioada_contabila"),
        pk=document_id,
        sters_la__isnull=True,
    )
    try:
        document = creeaza_document(
            actor=request.user,
            perioada_id=document_sursa.perioada_contabila_id,
            tip_document_id=document_sursa.tip_document_id,
            cont_financiar_id=document_sursa.cont_financiar_id,
            note=document_sursa.note or "",
            context=context_audit_din_request(request),
            predare_documente_id=document_sursa.predare_documente_id,
        )
    except TranzitieDocumentInvalida as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    return JsonResponse(
        {
            "document_id": str(document.pk),
            "detail_url": reverse("document_detaliu", kwargs={"document_id": document.pk}),
            "upload_init_url": reverse("upload_initiere", kwargs={"document_id": document.pk}),
        },
        status=201,
    )


@login_required
def document_detaliu(request, document_id):
    document = get_object_or_404(
        Document.objects.select_related(
            "firma",
            "perioada_contabila",
            "tip_document",
            "cont_financiar",
            "partener",
            "predare_documente",
        ),
        pk=document_id,
        sters_la__isnull=True,
    )
    comentarii = list(document.comentarii.all())
    autori = dict(
        Utilizator.objects.filter(
            pk__in=[comentariu.utilizator_id for comentariu in comentarii]
        ).values_list("pk", "nume")
    )
    for comentariu in comentarii:
        comentariu.autor_nume = autori.get(comentariu.utilizator_id, "Utilizator")
    fisiere = list(document.fisiere.filter(sters_la__isnull=True))
    fisiere_active = [fisier for fisier in fisiere if fisier.activ]
    numar_fisiere_procesate = sum(
        fisier.stare_procesare == FisierDocument.StareProcesare.PROCESAT
        for fisier in fisiere_active
    )
    extractie, sugestii_extractie = sugestii_pentru_document(document)
    if extractie and extractie.incredere is not None:
        extractie.incredere_procent = round(float(extractie.incredere) * 100)
    return render(
        request,
        "documente/detaliu.html",
        {
            "document": document,
            "fisiere": fisiere,
            "fisiere_active": fisiere_active,
            "numar_fisiere_active": len(fisiere_active),
            "numar_fisiere_procesate": numar_fisiere_procesate,
            "toate_fisierele_procesate": bool(
                fisiere_active and numar_fisiere_procesate == len(fisiere_active)
            ),
            "comentarii": comentarii,
            "istoric": IstoricStare.objects.filter(
                entitate_tip="document", entitate_id=document.pk
            ),
            "formular_acceptare": AcceptareDocumentForm(
                document=document,
                sugestii=sugestii_extractie,
            ),
            "extractie_structurata": extractie,
            "formular_mesaj": MesajForm(),
            "formular_motiv": MotivForm(),
            "formular_comentariu": ComentariuForm(),
            "formular_reclasificare": ReclasificareDocumentForm(document=document),
            "formular_partener": PartenerForm(),
            "poate_verifica": poate_verifica_documente(request.user),
            "poate_anula": poate_anula_document(request.user, document),
            "poate_comenta": poate_comenta_document(request.user, document),
            "poate_reclasifica": poate_reclasifica_document(request.user, document),
            "poate_atasa_fisiere": poate_atasa_fisiere(request.user, document),
            "este_autor": document.incarcat_de_id == request.user.pk,
            "permite_incarcare_serie": bool(
                document.stare == Document.Stare.DRAFT
                and document.incarcat_de_id == request.user.pk
            ),
        },
    )


@login_required
def verificare_documente(request):
    if not poate_verifica_documente(request.user):
        raise PermissionDenied

    stari_coada = (
        Document.Stare.TRIMIS,
        Document.Stare.IN_VERIFICARE,
        Document.Stare.NECESITA_CLARIFICARI,
        Document.Stare.ACCEPTAT,
    )
    documente_baza = Document.objects.filter(
        stare__in=stari_coada,
        sters_la__isnull=True,
    )
    rezumat_stari = {
        rand["stare"]: rand["total"]
        for rand in documente_baza.values("stare").annotate(total=Count("id"))
    }
    documente = documente_baza.select_related(
        "firma",
        "perioada_contabila",
        "tip_document",
        "cont_financiar",
        "partener",
        "predare_documente",
    )

    firme = list(Firma.objects.filter(activa=True).order_by("denumire"))
    firma_id = request.GET.get("firma", "")
    if firma_id and any(str(firma.pk) == firma_id for firma in firme):
        documente = documente.filter(firma_id=firma_id)
    else:
        firma_id = ""

    stare = request.GET.get("stare", "")
    if stare in stari_coada:
        documente = documente.filter(stare=stare)
    else:
        stare = ""

    try:
        luna = int(request.GET.get("luna", ""))
    except ValueError:
        luna = None
    if luna and 1 <= luna <= 12:
        documente = documente.filter(perioada_contabila__luna=luna)
    else:
        luna = None

    try:
        an = int(request.GET.get("an", ""))
    except ValueError:
        an = None
    if an and 2000 <= an <= 2200:
        documente = documente.filter(perioada_contabila__an=an)
    else:
        an = None

    prioritate = Case(
        When(stare=Document.Stare.TRIMIS, then=Value(1)),
        When(stare=Document.Stare.IN_VERIFICARE, then=Value(2)),
        When(stare=Document.Stare.NECESITA_CLARIFICARI, then=Value(3)),
        When(stare=Document.Stare.ACCEPTAT, then=Value(4)),
        default=Value(5),
        output_field=IntegerField(),
    )
    documente = documente.annotate(prioritate=prioritate).order_by(
        "prioritate",
        "creat_la",
    )
    pagina_documente = Paginator(documente, 50).get_page(request.GET.get("pagina"))
    return render(
        request,
        "documente/verificare.html",
        {
            "documente": pagina_documente,
            "firme": firme,
            "firma_selectata": firma_id,
            "stare_selectata": stare,
            "luna_selectata": luna,
            "an_selectat": an,
            "stari": [
                (valoare, eticheta)
                for valoare, eticheta in Document.Stare.choices
                if valoare in stari_coada
            ],
            "luni": range(1, 13),
            "total_coada": sum(rezumat_stari.values()),
            "total_filtrat": pagina_documente.paginator.count,
            "total_trimise": rezumat_stari.get(Document.Stare.TRIMIS, 0),
            "total_in_verificare": rezumat_stari.get(Document.Stare.IN_VERIFICARE, 0),
            "total_clarificari": rezumat_stari.get(Document.Stare.NECESITA_CLARIFICARI, 0),
            "total_acceptate": rezumat_stari.get(Document.Stare.ACCEPTAT, 0),
        },
    )


def _executa(request, document_id, functie, mesaj_succes, **kwargs):
    document = get_object_or_404(Document, pk=document_id, sters_la__isnull=True)
    try:
        functie(
            document_id=document.pk,
            actor=request.user,
            context=context_audit_din_request(request),
            **kwargs,
        )
    except TranzitieDocumentInvalida as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, mesaj_succes)
    return redirect("document_detaliu", document_id=document.pk)


@login_required
@require_POST
def document_trimitere(request, document_id):
    return _executa(request, document_id, trimite_document, "Documentul a fost trimis.")


@login_required
@require_POST
def document_trimitere_lot(request, document_id):
    get_object_or_404(Document, pk=document_id, sters_la__isnull=True)
    try:
        documente = trimite_documente_in_lot(
            document_ids=request.POST.getlist("document_ids"),
            actor=request.user,
            context=context_audit_din_request(request),
        )
    except TranzitieDocumentInvalida as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse({"status": "trimis", "total": len(documente)})


@login_required
@require_POST
def document_preluare(request, document_id):
    return _executa(request, document_id, preia_document, "Documentul este în verificare.")


@login_required
@require_POST
def document_reclasificare(request, document_id):
    document = get_object_or_404(
        Document.objects.select_related("perioada_contabila"),
        pk=document_id,
        sters_la__isnull=True,
    )
    formular = ReclasificareDocumentForm(request.POST, document=document)
    if not formular.is_valid():
        messages.error(request, "Tipul sau contul financiar este invalid.")
        return redirect("document_detaliu", document_id=document.pk)
    return _executa(
        request,
        document.pk,
        reclasifica_document,
        "Documentul a fost reclasificat.",
        tip_document_id=formular.cleaned_data["tip_document"].pk,
        cont_financiar_id=(
            formular.cleaned_data["cont_financiar"].pk
            if formular.cleaned_data["cont_financiar"]
            else None
        ),
    )


@login_required
@require_POST
def document_clarificare(request, document_id):
    formular = MesajForm(request.POST)
    if not formular.is_valid():
        messages.error(request, "Mesajul de clarificare este obligatoriu.")
        return redirect("document_detaliu", document_id=document_id)
    return _executa(
        request,
        document_id,
        cere_clarificari,
        "Clarificarea a fost cerută.",
        mesaj=formular.cleaned_data["mesaj"],
    )


@login_required
@require_POST
def document_raspuns(request, document_id):
    formular = MesajForm(request.POST)
    if not formular.is_valid():
        messages.error(request, "Răspunsul este obligatoriu.")
        return redirect("document_detaliu", document_id=document_id)
    return _executa(
        request,
        document_id,
        raspunde_clarificarii,
        "Răspunsul a fost trimis.",
        mesaj=formular.cleaned_data["mesaj"],
    )


@login_required
@require_POST
def document_acceptare(request, document_id):
    document = get_object_or_404(Document, pk=document_id, sters_la__isnull=True)
    formular = AcceptareDocumentForm(request.POST, document=document)
    if not formular.is_valid():
        messages.error(request, "Metadatele documentului sunt invalide.")
        return redirect("document_detaliu", document_id=document.pk)
    try:
        accepta_document(
            document_id=document.pk,
            actor=request.user,
            context=context_audit_din_request(request),
            **{
                camp: formular.cleaned_data[camp]
                for camp in (
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
                )
                if camp != "partener"
            },
            partener_id=(
                formular.cleaned_data["partener"].pk if formular.cleaned_data["partener"] else None
            ),
        )
    except DocumentDuplicat:
        messages.error(request, "Documentul există deja pentru același partener, serie și număr.")
    except TranzitieDocumentInvalida as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Documentul a fost acceptat.")
    return redirect("document_detaliu", document_id=document.pk)


@login_required
@require_POST
def document_partener_nou(request, document_id):
    document = get_object_or_404(Document, pk=document_id, sters_la__isnull=True)
    if not poate_verifica_documente(request.user) or document.stare != Document.Stare.IN_VERIFICARE:
        raise PermissionDenied
    formular = PartenerForm(request.POST)
    if not formular.is_valid():
        messages.error(request, "Partenerul nu a fost creat. Verifică datele introduse.")
        return redirect("document_detaliu", document_id=document.pk)
    try:
        partener = creeaza_partener(
            firma_id=document.firma_id,
            utilizator=request.user,
            date=formular.cleaned_data,
            context=context_audit_din_request(request),
        )
    except CUIDuplicatPartener:
        messages.error(request, "Există deja un partener cu acest CUI în firma clientă.")
    else:
        messages.success(
            request,
            f"Partenerul {partener.denumire} a fost creat și poate fi selectat la acceptare.",
        )
    return redirect("document_detaliu", document_id=document.pk)


@login_required
@require_POST
def document_procesare(request, document_id):
    return _executa(
        request,
        document_id,
        proceseaza_document,
        "Documentul a fost marcat procesat.",
    )


@login_required
@require_POST
def document_retur(request, document_id):
    formular = MotivForm(request.POST)
    return _executa(
        request,
        document_id,
        returneaza_in_verificare,
        "Documentul a revenit în verificare.",
        motiv=formular.data.get("motiv", ""),
    )


@login_required
@require_POST
def document_anulare(request, document_id):
    formular = MotivForm(request.POST)
    return _executa(
        request,
        document_id,
        anuleaza_document,
        "Documentul a fost anulat.",
        motiv=formular.data.get("motiv", ""),
    )


@login_required
@require_POST
def document_stergere(request, document_id):
    document = get_object_or_404(Document, pk=document_id, sters_la__isnull=True)
    formular = MotivForm(request.POST)
    try:
        sterge_ciorna(
            document_id=document.pk,
            actor=request.user,
            motiv=formular.data.get("motiv", ""),
            context=context_audit_din_request(request),
        )
    except TranzitieDocumentInvalida as exc:
        messages.error(request, str(exc))
        return redirect("document_detaliu", document_id=document.pk)
    messages.success(request, "Ciorna a fost ștearsă.")
    return redirect("perioada_detaliu", perioada_id=document.perioada_contabila_id)


@login_required
@require_POST
def document_comentariu(request, document_id):
    formular = ComentariuForm(request.POST)
    if not formular.is_valid():
        messages.error(request, "Comentariul nu poate fi gol.")
        return redirect("document_detaliu", document_id=document_id)
    return _executa(
        request,
        document_id,
        adauga_comentariu,
        "Comentariul a fost adăugat.",
        text=formular.cleaned_data["text"],
    )


@login_required
@require_POST
def upload_initiere(request, document_id):
    get_object_or_404(Document, pk=document_id, sters_la__isnull=True)
    try:
        dimensiune = int(request.POST.get("dimensiune", "0"))
        rezultat = initiaza_upload(
            document_id=document_id,
            actor=request.user,
            nume_original=request.POST.get("nume", ""),
            content_type=request.POST.get("content_type"),
            dimensiune_declarata=dimensiune,
            request=request,
            inlocuieste_fisier_id=request.POST.get("inlocuieste_fisier_id") or None,
        )
    except (EroareUpload, ValueError) as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse(
        {
            "intentie_id": str(rezultat.intentie.pk),
            "upload_url": rezultat.upload_url,
            "finalize_url": reverse(
                "upload_finalizare",
                kwargs={"intentie_id": rezultat.intentie.pk},
            ),
            "method": "PUT",
            "headers": rezultat.headers,
        }
    )


@csrf_exempt
@require_http_methods(["PUT"])
def upload_local_put(request, intentie_id):
    try:
        lungime = int(request.headers.get("Content-Length", "0"))
        if lungime < 1 or lungime > settings.DOCUMENT_UPLOAD_MAX_BYTES:
            raise EroareUpload("Fișierul trebuie să aibă cel mult 25 MB.")
        primeste_upload_local(
            intentie_id=intentie_id,
            token=request.GET.get("token", ""),
            content_type=request.content_type,
            continut=request.body,
        )
    except (EroareUpload, ValueError) as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse({}, status=204)


@login_required
@require_POST
def upload_finalizare(request, intentie_id):
    get_object_or_404(IntentieUpload, pk=intentie_id)
    try:
        fisier = finalizeaza_upload(
            intentie_id=intentie_id,
            actor=request.user,
            context=context_audit_din_request(request),
        )
    except EroareUpload as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse(
        {
            "fisier_id": str(fisier.pk),
            "stare_procesare": fisier.stare_procesare,
            "eroare": fisier.eroare_procesare,
        }
    )


@login_required
@require_POST
def fisier_stergere(request, fisier_id):
    fisier = get_object_or_404(
        FisierDocument,
        pk=fisier_id,
        activ=True,
        sters_la__isnull=True,
    )
    try:
        sterge_fisier(
            fisier_id=fisier.pk,
            actor=request.user,
            context=context_audit_din_request(request),
        )
    except EroareUpload as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Fișierul a fost eliminat din ciornă.")
    return redirect("document_detaliu", document_id=fisier.document_id)


def _redirect_acces_fisier(request, fisier_id, *, descarcare):
    fisier = get_object_or_404(
        FisierDocument,
        pk=fisier_id,
        sters_la__isnull=True,
        document__sters_la__isnull=True,
    )
    try:
        url = url_acces_fisier(
            request=request,
            fisier=fisier,
            descarcare=descarcare,
        )
    except EroareAccesFisier as exc:
        messages.error(request, str(exc))
        return redirect("document_detaliu", document_id=fisier.document_id)
    return redirect(url)


@login_required
def fisier_deschidere(request, fisier_id):
    return _redirect_acces_fisier(request, fisier_id, descarcare=False)


@login_required
def fisier_descarcare(request, fisier_id):
    return _redirect_acces_fisier(request, fisier_id, descarcare=True)


def fisier_local_semnat(request):
    try:
        rezultat = continut_local_semnat(token=request.GET.get("token", ""))
    except EroareAccesFisier as exc:
        return HttpResponse(str(exc), status=404, content_type="text/plain; charset=utf-8")
    response = HttpResponse(rezultat.continut, content_type=rezultat.content_type)
    response["Content-Disposition"] = rezultat.content_disposition
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    response["Cross-Origin-Resource-Policy"] = "same-origin"
    return response
