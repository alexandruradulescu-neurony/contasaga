from datetime import date

from django import forms

from .models import CerintaDocumentPerioada

LUNI = (
    (1, "Ianuarie"),
    (2, "Februarie"),
    (3, "Martie"),
    (4, "Aprilie"),
    (5, "Mai"),
    (6, "Iunie"),
    (7, "Iulie"),
    (8, "August"),
    (9, "Septembrie"),
    (10, "Octombrie"),
    (11, "Noiembrie"),
    (12, "Decembrie"),
)


class DeschiderePerioadaForm(forms.Form):
    luna = forms.TypedChoiceField(
        choices=LUNI,
        coerce=int,
        label="Luna",
    )
    an = forms.IntegerField(min_value=2000, max_value=2100, initial=date.today().year, label="An")
    termen_predare = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
        label="Termen de predare",
    )
    observatii = forms.CharField(required=False, widget=forms.Textarea, label="Observații")


class ActualizareCerintaForm(forms.Form):
    status = forms.ChoiceField(choices=CerintaDocumentPerioada.Status.choices, label="Status")
    numar_documente_declarat = forms.IntegerField(
        required=False, min_value=1, label="Număr documente declarat"
    )
    observatie = forms.CharField(required=False, widget=forms.Textarea, label="Observație")

    def clean(self):
        cleaned_data = super().clean()
        if (
            cleaned_data.get("status") == "nu_se_aplica"
            and not cleaned_data.get("observatie", "").strip()
        ):
            self.add_error("observatie", "Explică de ce documentul nu se aplică acestei luni.")
        return cleaned_data


class RedeschiderePerioadaForm(forms.Form):
    motiv = forms.CharField(widget=forms.Textarea, label="Motivul redeschiderii")
