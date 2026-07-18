from django import forms
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from firme.models import Firma

from .invitations import ROLURI_CLIENT, ROLURI_INTERNE, roluri_permise_pentru
from .models import Utilizator


class InvitatieForm(forms.Form):
    email = forms.EmailField(label="Email")
    rol = forms.ChoiceField(label="Rol")
    firma = forms.ModelChoiceField(
        queryset=Firma.objects.none(),
        required=False,
        label="Firmă clientă",
        help_text="Se completează numai pentru utilizatorii client.",
    )

    def __init__(self, *args, utilizator, **kwargs):
        super().__init__(*args, **kwargs)
        roluri = roluri_permise_pentru(utilizator)
        self.fields["rol"].choices = [
            (valoare, eticheta) for valoare, eticheta in Utilizator.Rol.choices if valoare in roluri
        ]
        self.fields["firma"].queryset = Firma.objects.order_by("denumire")

    def clean_email(self):
        return self.cleaned_data["email"].strip().lower()

    def clean(self):
        cleaned_data = super().clean()
        rol = cleaned_data.get("rol")
        firma = cleaned_data.get("firma")
        if rol in ROLURI_INTERNE and firma:
            self.add_error("firma", "Invitația internă nu se leagă de o firmă clientă.")
        if rol in ROLURI_CLIENT and not firma:
            self.add_error("firma", "Selectează firma clientă.")
        return cleaned_data


class AcceptareInvitatieForm(forms.Form):
    nume = forms.CharField(max_length=255, label="Nume complet")
    telefon = forms.CharField(max_length=30, required=False, label="Telefon")
    password1 = forms.CharField(label="Parolă", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Confirmă parola", widget=forms.PasswordInput)

    def __init__(self, *args, invitatie, **kwargs):
        super().__init__(*args, **kwargs)
        self.invitatie = invitatie

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get("password1")
        password2 = cleaned_data.get("password2")
        if password1 and password2 and password1 != password2:
            self.add_error("password2", "Parolele nu coincid.")
        elif password1:
            try:
                validate_password(
                    password1,
                    Utilizator(
                        email=self.invitatie.email,
                        nume=cleaned_data.get("nume", ""),
                        rol=self.invitatie.rol,
                    ),
                )
            except ValidationError as exc:
                self.add_error("password2", exc)
        return cleaned_data
