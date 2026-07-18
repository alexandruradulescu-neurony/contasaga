from django import forms

from .models import ConfigurareDocumentFirma, ContFinanciar, TipDocument


class ConfigurareDocumentForm(forms.ModelForm):
    class Meta:
        model = ConfigurareDocumentFirma
        fields = (
            "tip_document",
            "obligatoriu",
            "frecventa",
            "termen_predare_zi",
            "activ",
            "observatii",
        )
        labels = {
            "tip_document": "Tip de document",
            "obligatoriu": "Obligatoriu în checklist",
            "frecventa": "Frecvență",
            "termen_predare_zi": "Zi recomandată pentru predare",
            "activ": "Configurare activă",
            "observatii": "Observații",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["tip_document"].queryset = TipDocument.objects.filter(activ=True)


class ContFinanciarForm(forms.ModelForm):
    class Meta:
        model = ContFinanciar
        fields = ("tip", "denumire", "banca", "iban", "moneda", "activ")
        labels = {
            "tip": "Tip cont",
            "denumire": "Denumire",
            "banca": "Bancă",
            "iban": "IBAN",
            "moneda": "Monedă",
            "activ": "Cont activ",
        }

    def clean_iban(self):
        return (self.cleaned_data.get("iban") or "").replace(" ", "").upper() or None

    def clean_moneda(self):
        return self.cleaned_data["moneda"].strip().upper()
