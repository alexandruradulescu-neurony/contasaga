from django import forms
from django.contrib.auth.forms import ReadOnlyPasswordHashField
from django.contrib.auth.password_validation import validate_password

from firme.models import FirmaContabilitate

from .models import Utilizator

ROLURI_INTERNE = {"admin_cabinet", "contabil_coordonator", "contabil"}


class FirmaContabilitateMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.cabinet_id:
            self.fields["firma_contabilitate"].initial = self.instance.cabinet_id

    def clean(self):
        cleaned_data = super().clean()
        rol = cleaned_data.get("rol")
        firma_contabilitate = cleaned_data.get("firma_contabilitate")
        if rol in ROLURI_INTERNE and not firma_contabilitate:
            self.add_error(
                "firma_contabilitate",
                "Rolurile interne trebuie să aparțină unei firme de contabilitate.",
            )
        if rol not in ROLURI_INTERNE and firma_contabilitate:
            self.add_error(
                "firma_contabilitate",
                "Acest rol nu poate aparține unei firme de contabilitate.",
            )
        return cleaned_data

    def _aplica_contract_rol(self, user):
        firma_contabilitate = self.cleaned_data.get("firma_contabilitate")
        user.cabinet_id = firma_contabilitate.pk if firma_contabilitate else None
        este_superuser = user.rol == "superuser_platforma"
        user.is_staff = este_superuser
        user.is_superuser = este_superuser


class UtilizatorCreationForm(FirmaContabilitateMixin, forms.ModelForm):
    firma_contabilitate = forms.ModelChoiceField(
        queryset=FirmaContabilitate.objects.all(),
        required=False,
        label="Firmă de contabilitate",
    )
    password1 = forms.CharField(label="Parolă", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Confirmă parola", widget=forms.PasswordInput)

    class Meta:
        model = Utilizator
        fields = ("email", "nume", "rol", "firma_contabilitate")

    def clean_password2(self):
        password1 = self.cleaned_data.get("password1")
        password2 = self.cleaned_data.get("password2")
        if password1 and password2 and password1 != password2:
            raise forms.ValidationError("Parolele nu coincid")
        if password2:
            utilizator = Utilizator(
                email=self.cleaned_data.get("email", ""),
                nume=self.cleaned_data.get("nume", ""),
            )
            validate_password(password2, utilizator)
        return password2

    def save(self, commit=True):
        user = super().save(commit=False)
        self._aplica_contract_rol(user)
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
        return user


class UtilizatorChangeForm(FirmaContabilitateMixin, forms.ModelForm):
    firma_contabilitate = forms.ModelChoiceField(
        queryset=FirmaContabilitate.objects.all(),
        required=False,
        label="Firmă de contabilitate",
    )
    password = ReadOnlyPasswordHashField(label="Parolă")

    class Meta:
        model = Utilizator
        fields = (
            "email",
            "password",
            "nume",
            "telefon",
            "rol",
            "firma_contabilitate",
            "is_active",
            "is_staff",
            "is_superuser",
            "last_login",
        )

    def save(self, commit=True):
        user = super().save(commit=False)
        self._aplica_contract_rol(user)
        if commit:
            user.save()
        return user
