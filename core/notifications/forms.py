from django import forms

from . import services
from .models import EmailSettings


class EmailSettingsForm(forms.ModelForm):
    """The password is typed here, scrambled, and never shown again. Blank keeps the saved one."""

    password = forms.CharField(
        required=False,
        strip=False,
        widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password"}),
        help_text="App Password from your mail provider (Gmail, Outlook), not your normal password.",
    )

    class Meta:
        model = EmailSettings
        fields = ["sending_on", "host", "port", "security", "username", "password",
                  "from_name", "from_address", "reply_to"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.password_encrypted:
            self.fields["password"].help_text = (
                "●●●● saved. Leave blank to keep it, or type a new App Password to replace it."
            )

    def clean_password(self):
        typed = self.cleaned_data["password"]
        is_gmail = "gmail" in (self.cleaned_data.get("host") or "").lower()
        if typed and is_gmail and len(typed.replace(" ", "")) != 16:
            raise forms.ValidationError(
                "This is not a Gmail App Password: those are 16 letters, like 'abcd efgh ijkl mnop'. "
                "Make one at myaccount.google.com/apppasswords (2-Step Verification must be on)."
            )
        if typed:
            try:
                self.encrypted_password = services.encrypt_password(typed)
            except services.EmailSettingsError as error:
                raise forms.ValidationError(str(error)) from error
        return ""  # the plain password goes no further than this form

    def save(self, commit=True):
        if getattr(self, "encrypted_password", None):
            self.instance.password_encrypted = self.encrypted_password
        return super().save(commit)
