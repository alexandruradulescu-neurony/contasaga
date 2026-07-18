from django import forms

from .models import Firma, Partener


class FirmaForm(forms.ModelForm):
    class Meta:
        model = Firma
        fields = (
            "cui",
            "denumire",
            "adresa",
            "email_contact",
            "telefon_contact",
            "activa",
        )
        labels = {
            "cui": "CUI",
            "denumire": "Denumire",
            "adresa": "Adresă",
            "email_contact": "Email de contact",
            "telefon_contact": "Telefon de contact",
            "activa": "Firmă activă",
        }

    def clean_cui(self):
        return self.cleaned_data["cui"].strip().upper()


class PartenerForm(forms.ModelForm):
    class Meta:
        model = Partener
        fields = ("tip", "cui", "denumire", "tara")
        labels = {
            "tip": "Tip partener",
            "cui": "CUI / cod fiscal",
            "denumire": "Denumire",
            "tara": "Țară (cod ISO)",
        }

    def clean_cui(self):
        return (self.cleaned_data.get("cui") or "").strip().upper() or None

    def clean_denumire(self):
        return self.cleaned_data["denumire"].strip()

    def clean_tara(self):
        return self.cleaned_data["tara"].strip().upper()
