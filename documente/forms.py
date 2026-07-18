from django import forms

from firme.models import ContFinanciar, Partener, TipDocument

from .models import Document


class DocumentNouForm(forms.Form):
    tip_document = forms.ModelChoiceField(
        queryset=TipDocument.objects.none(),
        label="Tip document",
    )
    cont_financiar = forms.ModelChoiceField(
        queryset=ContFinanciar.objects.none(),
        required=False,
        label="Cont financiar",
    )
    note = forms.CharField(required=False, widget=forms.Textarea, label="Notă")

    def __init__(self, *args, perioada, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["tip_document"].queryset = TipDocument.objects.filter(activ=True)
        self.fields["cont_financiar"].queryset = ContFinanciar.objects.filter(
            firma=perioada.firma,
            activ=True,
        )


class ReclasificareDocumentForm(DocumentNouForm):
    note = None

    def __init__(self, *args, document, **kwargs):
        super().__init__(*args, perioada=document.perioada_contabila, **kwargs)
        self.fields["tip_document"].initial = document.tip_document_id
        self.fields["cont_financiar"].initial = document.cont_financiar_id


class AcceptareDocumentForm(forms.Form):
    partener = forms.ModelChoiceField(
        queryset=Partener.objects.none(),
        required=False,
        label="Partener",
    )
    directie = forms.ChoiceField(
        choices=(("", "—"), *Document.Directie.choices),
        required=False,
        label="Direcție",
    )
    serie = forms.CharField(max_length=20, required=False, label="Serie")
    numar = forms.CharField(max_length=30, required=False, label="Număr")
    data_document = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
        label="Data documentului",
    )
    data_scadenta = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
        label="Data scadenței",
    )
    moneda = forms.CharField(max_length=3, initial="RON", label="Monedă")
    valoare_fara_tva = forms.DecimalField(
        max_digits=14,
        decimal_places=2,
        required=False,
        label="Valoare fără TVA",
    )
    valoare_tva = forms.DecimalField(
        max_digits=14,
        decimal_places=2,
        required=False,
        label="TVA",
    )
    valoare_totala = forms.DecimalField(
        max_digits=14,
        decimal_places=2,
        required=False,
        label="Valoare totală",
    )
    retentie_extinsa_pana_la = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
        label="Retenție extinsă până la",
    )

    def __init__(self, *args, document, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["partener"].queryset = Partener.objects.filter(
            firma_id=document.firma_id,
            activ=True,
        )
        initial = {
            "partener": document.partener_id,
            "directie": document.directie,
            "serie": document.serie,
            "numar": document.numar,
            "data_document": document.data_document,
            "data_scadenta": document.data_scadenta,
            "moneda": document.moneda,
            "valoare_fara_tva": document.valoare_fara_tva,
            "valoare_tva": document.valoare_tva,
            "valoare_totala": document.valoare_totala,
            "retentie_extinsa_pana_la": document.retentie_extinsa_pana_la,
        }
        for nume, valoare in initial.items():
            self.fields[nume].initial = valoare


class MesajForm(forms.Form):
    mesaj = forms.CharField(widget=forms.Textarea, label="Mesaj")


class MotivForm(forms.Form):
    motiv = forms.CharField(required=False, widget=forms.Textarea, label="Motiv")


class ComentariuForm(forms.Form):
    text = forms.CharField(widget=forms.Textarea, label="Comentariu")
