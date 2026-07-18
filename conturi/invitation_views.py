from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.audit import context_audit_din_request
from notificari.services import trimite_email_invitatie

from .invitation_forms import AcceptareInvitatieForm, InvitatieForm
from .invitations import (
    EroareInvitatie,
    accepta_invitatie,
    anuleaza_invitatie,
    creeaza_invitatie,
    obtine_invitatie_publica,
    poate_gestiona_invitatii,
)
from .models import Invitatie


@login_required
def invitatii(request):
    if not poate_gestiona_invitatii(request.user):
        raise PermissionDenied

    form = InvitatieForm(request.POST or None, utilizator=request.user)
    if request.method == "POST" and form.is_valid():
        try:
            rezultat = creeaza_invitatie(
                utilizator=request.user,
                email=form.cleaned_data["email"],
                rol=form.cleaned_data["rol"],
                firma=form.cleaned_data["firma"],
                context=context_audit_din_request(request),
            )
        except EroareInvitatie as exc:
            form.add_error(None, str(exc))
        else:
            cale = reverse("invitatie_acceptare", kwargs={"token": rezultat.token})
            link_acceptare = request.build_absolute_uri(cale)
            destinatie = (
                form.cleaned_data["firma"].denumire
                if form.cleaned_data["firma"]
                else "firma de contabilitate"
            )
            email_trimis = trimite_email_invitatie(
                email=form.cleaned_data["email"],
                link_acceptare=link_acceptare,
                destinatie=destinatie,
            )
            return render(
                request,
                "conturi/invitatie_creata.html",
                {
                    "link_acceptare": link_acceptare,
                    "email_trimis": email_trimis,
                },
            )

    lista = Invitatie.objects.select_related("firma", "cabinet").all()
    return render(request, "conturi/invitatii.html", {"form": form, "invitatii": lista})


@login_required
@require_POST
def invitatie_anulare(request, invitatie_id):
    invitatie = get_object_or_404(
        Invitatie.objects.select_related("firma", "cabinet"), pk=invitatie_id
    )
    try:
        anuleaza_invitatie(
            utilizator=request.user,
            invitatie=invitatie,
            context=context_audit_din_request(request),
        )
    except EroareInvitatie as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Invitația a fost anulată.")
    return redirect("invitatii")


def invitatie_acceptare(request, token):
    try:
        invitatie = obtine_invitatie_publica(token)
    except EroareInvitatie as exc:
        return render(
            request,
            "conturi/invitatie_invalida.html",
            {"mesaj": str(exc)},
            status=400,
        )

    if invitatie.cont_existent:
        if not request.user.is_authenticated:
            parametri = urlencode({"next": request.path})
            return redirect(f"{reverse('login')}?{parametri}")
        if request.user.email.lower() != invitatie.email.lower():
            raise PermissionDenied("Invitația aparține altui cont.")
        if request.method == "POST":
            try:
                accepta_invitatie(
                    token=token,
                    utilizator_autentificat=request.user,
                    nume=None,
                    telefon=None,
                    parola=None,
                    context=context_audit_din_request(request),
                )
            except EroareInvitatie as exc:
                return render(
                    request,
                    "conturi/invitatie_invalida.html",
                    {"mesaj": str(exc)},
                    status=400,
                )
            messages.success(request, "Accesul la firmă a fost adăugat contului tău.")
            return redirect("dashboard")
        return render(
            request,
            "conturi/invitatie_acceptare.html",
            {"invitatie": invitatie, "cont_existent": True},
        )

    form = AcceptareInvitatieForm(request.POST or None, invitatie=invitatie)
    if request.method == "POST" and form.is_valid():
        try:
            accepta_invitatie(
                token=token,
                utilizator_autentificat=request.user,
                nume=form.cleaned_data["nume"],
                telefon=form.cleaned_data["telefon"],
                parola=form.cleaned_data["password1"],
                context=context_audit_din_request(request),
            )
        except EroareInvitatie as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(request, "Contul a fost creat. Te poți autentifica acum.")
            return redirect("login")
    return render(
        request,
        "conturi/invitatie_acceptare.html",
        {"invitatie": invitatie, "form": form, "cont_existent": False},
    )
