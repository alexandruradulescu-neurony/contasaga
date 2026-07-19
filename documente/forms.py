from django import forms

from firme.models import ConfigurareDocumentFirma, ContFinanciar, Partener, TipDocument

from .models import AnalizaFisierInbox, Document


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

    def __init__(self, *args, document, sugestii=None, **kwargs):
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
        for nume, valoare in (sugestii or {}).items():
            if nume in initial and initial[nume] in (None, "") and valoare not in (None, ""):
                initial[nume] = valoare
        for nume, valoare in initial.items():
            self.fields[nume].initial = valoare


class MesajForm(forms.Form):
    mesaj = forms.CharField(widget=forms.Textarea, label="Mesaj")


class MotivForm(forms.Form):
    motiv = forms.CharField(required=False, widget=forms.Textarea, label="Motiv")


class ComentariuForm(forms.Form):
    text = forms.CharField(widget=forms.Textarea, label="Comentariu")


class ClasificareFisierInboxForm(forms.Form):
    tip_document = forms.ModelChoiceField(
        queryset=TipDocument.objects.none(),
        label="Tip document",
    )
    cont_financiar = forms.ModelChoiceField(
        queryset=ContFinanciar.objects.none(),
        required=False,
        label="Cont financiar",
    )
    directie = forms.ChoiceField(
        choices=(("", "Selectează"), *Document.Directie.choices),
        label="Direcție",
    )
    observatii = forms.CharField(
        required=False,
        max_length=2000,
        widget=forms.Textarea(attrs={"rows": 2}),
        label="Observații",
    )

    def __init__(self, *args, fisier, **kwargs):
        super().__init__(*args, **kwargs)
        configurate = ConfigurareDocumentFirma.objects.filter(
            firma_id=fisier.firma_id,
            activ=True,
            tip_document__activ=True,
        ).values_list("tip_document_id", flat=True)
        tipuri = TipDocument.objects.filter(activ=True)
        if configurate.exists():
            tipuri = tipuri.filter(pk__in=configurate)
        self.fields["tip_document"].queryset = tipuri.order_by("denumire")
        self.fields["cont_financiar"].queryset = ContFinanciar.objects.filter(
            firma_id=fisier.firma_id,
            activ=True,
        ).order_by("denumire")

        try:
            analiza = fisier.analiza
        except AnalizaFisierInbox.DoesNotExist:
            return
        if analiza.status == AnalizaFisierInbox.Status.FINALIZATA:
            self.initial.update(
                {
                    "tip_document": analiza.tip_document_sugerat_id,
                    "cont_financiar": analiza.cont_financiar_sugerat_id,
                    "directie": analiza.directie_sugerata,
                }
            )


class SegmentDocumentInboxForm(forms.Form):
    pagina_start = forms.IntegerField(min_value=1, label="De la pagina")
    pagina_sfarsit = forms.IntegerField(min_value=1, label="Până la pagina")
    tip_document = forms.ModelChoiceField(
        queryset=TipDocument.objects.none(),
        label="Tip document",
    )
    cont_financiar = forms.ModelChoiceField(
        queryset=ContFinanciar.objects.none(),
        required=False,
        label="Cont financiar",
    )
    directie = forms.ChoiceField(
        choices=(("", "Selectează"), *Document.Directie.choices),
        label="Direcție",
    )
    observatii = forms.CharField(
        required=False,
        max_length=2000,
        widget=forms.Textarea(attrs={"rows": 2}),
        label="Observații",
    )

    def __init__(self, *args, fisier, **kwargs):
        super().__init__(*args, **kwargs)
        configurate = ConfigurareDocumentFirma.objects.filter(
            firma_id=fisier.firma_id,
            activ=True,
            tip_document__activ=True,
        ).values_list("tip_document_id", flat=True)
        tipuri = TipDocument.objects.filter(activ=True)
        if configurate.exists():
            tipuri = tipuri.filter(pk__in=configurate)
        self.fields["tip_document"].queryset = tipuri.order_by("denumire")
        self.fields["cont_financiar"].queryset = ContFinanciar.objects.filter(
            firma_id=fisier.firma_id,
            activ=True,
        ).order_by("denumire")


class BaseSegmentDocumentInboxFormSet(forms.BaseFormSet):
    def __init__(self, *args, fisier, **kwargs):
        self.fisier = fisier
        super().__init__(*args, **kwargs)

    def get_form_kwargs(self, index):
        return {**super().get_form_kwargs(index), "fisier": self.fisier}

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        numar_pagini = self.fisier.analiza.numar_pagini or 0
        pagina_asteptata = 1
        for formular in self.forms:
            start = formular.cleaned_data["pagina_start"]
            sfarsit = formular.cleaned_data["pagina_sfarsit"]
            if start != pagina_asteptata or sfarsit < start or sfarsit > numar_pagini:
                raise forms.ValidationError(
                    "Intervalele trebuie să acopere toate paginile, în ordine, fără goluri "
                    "sau suprapuneri."
                )
            pagina_asteptata = sfarsit + 1
        if pagina_asteptata != numar_pagini + 1:
            raise forms.ValidationError("Ultima pagină a originalului nu este acoperită.")


SegmentDocumentInboxFormSet = forms.formset_factory(
    SegmentDocumentInboxForm,
    formset=BaseSegmentDocumentInboxFormSet,
    extra=0,
    min_num=1,
    validate_min=True,
    max_num=100,
    validate_max=True,
)
