from django import forms

from .models import PredareDocumente


class ProgramarePredareForm(forms.Form):
    metoda = forms.ChoiceField(choices=PredareDocumente.Metoda.choices, label="Metodă")
    predat_de = forms.CharField(max_length=255, required=False, label="Predat de")
    numar_cutii = forms.IntegerField(min_value=0, initial=1, label="Număr de cutii")
    data_programata = forms.DateTimeField(
        required=False,
        label="Data programată",
        input_formats=("%Y-%m-%dT%H:%M",),
        widget=forms.DateTimeInput(
            format="%Y-%m-%dT%H:%M",
            attrs={"type": "datetime-local"},
        ),
    )
    observatii = forms.CharField(required=False, widget=forms.Textarea, label="Observații")

    def clean(self):
        date = super().clean()
        metoda = date.get("metoda")
        if metoda == PredareDocumente.Metoda.EXCLUSIV_DIGITAL:
            date["numar_cutii"] = 0
            date["data_programata"] = None
            return date
        if not (date.get("predat_de") or "").strip():
            self.add_error("predat_de", "Numele persoanei care predă este obligatoriu.")
        if (date.get("numar_cutii") or 0) < 1:
            self.add_error("numar_cutii", "Predarea fizică necesită cel puțin o cutie.")
        if date.get("data_programata") is None:
            self.add_error("data_programata", "Data programată este obligatorie.")
        return date


class DigitizareForm(forms.Form):
    numar_documente_estimat = forms.IntegerField(
        required=False,
        min_value=1,
        label="Număr estimat de documente",
        help_text="Opțional. Poți actualiza estimarea pe parcurs.",
    )
