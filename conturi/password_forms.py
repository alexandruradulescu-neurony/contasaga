from django import forms
from django.contrib.auth.forms import PasswordChangeForm, SetPasswordForm


class SchimbareParolaForm(PasswordChangeForm):
    def save(self, commit=True):
        user = self.user
        user.set_password(self.cleaned_data["new_password1"])
        if commit:
            user.save(update_fields=["password"])
        return user


class CerereResetParolaForm(forms.Form):
    email = forms.EmailField(label="Email")


class SetareParolaNouaForm(SetPasswordForm):
    pass
