from django import forms
from django.contrib.auth.forms import UserChangeForm

from .models import User


class LowerCaseEmailMixin:
    """Emails are stored lower-case, so check "already used" on the lower-case form too.
    Without this, inviting "Ravi@Acme.com" when ravi@acme.com exists crashes instead of saying so."""

    def clean_email(self):
        return self.cleaned_data["email"].strip().lower()


class OTPCodeForm(forms.Form):
    token = forms.CharField(
        label="6-digit code",
        max_length=6,
        min_length=6,
        widget=forms.TextInput(
            attrs={"autocomplete": "one-time-code", "inputmode": "numeric", "autofocus": True}
        ),
        help_text="Open your authenticator app and type the code shown for Group ERP.",
    )


class UserInviteForm(LowerCaseEmailMixin, forms.ModelForm):
    """Admin 'add user' form. No password: the user sets it from the invite email."""

    class Meta:
        model = User
        fields = ["email", "first_name", "last_name", "is_external"]


class UserEditForm(LowerCaseEmailMixin, UserChangeForm):
    """Admin 'change user' form, with the same lower-case email check."""

    class Meta(UserChangeForm.Meta):
        model = User
