from django import forms

from .models import User


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


class UserInviteForm(forms.ModelForm):
    """Admin 'add user' form. No password: the user sets it from the invite email."""

    class Meta:
        model = User
        fields = ["email", "first_name", "last_name", "is_external"]
