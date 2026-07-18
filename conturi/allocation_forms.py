from django import forms

from firme.models import Firma

from .models import Utilizator


class AlocareForm(forms.Form):
    utilizator = forms.ModelChoiceField(
        queryset=Utilizator.objects.none(),
        label="Membru al firmei de contabilitate",
    )
    firma = forms.ModelChoiceField(queryset=Firma.objects.none(), label="Firmă clientă")

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["utilizator"].queryset = Utilizator.objects.filter(
            cabinet_id=actor.cabinet_id,
            rol__in=("admin_cabinet", "contabil_coordonator", "contabil"),
            is_active=True,
        ).order_by("nume")
        self.fields["firma"].queryset = Firma.objects.order_by("denumire")
