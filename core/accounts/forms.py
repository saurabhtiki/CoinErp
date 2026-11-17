from django import forms
from django.contrib.auth.forms import UserChangeForm

from core.registry import all_apps

from .models import Role, User


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
        help_text="Open your authenticator app and type the code shown for Coin.",
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


class AppTickBoxes(forms.CheckboxSelectMultiple):
    """Tick boxes that show each app's description as a tooltip."""

    def __init__(self, *args, tooltips=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.tooltips = tooltips or {}

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        option["attrs"]["title"] = self.tooltips.get(value, "")
        return option


class RoleForm(forms.ModelForm):
    """Role screen: apps are tick boxes, not typed codes. Example: tick Tasks and Masters -> ["tasks", "masters"]."""

    allowed_apps = forms.MultipleChoiceField(
        required=False, label="Apps this role opens",
        help_text="Tick each app people with this role may open. Hover over an app to see what it holds.",
    )

    class Meta:
        model = Role
        fields = ["name", "allowed_apps", "own_records_only", "requires_2fa"]
        help_texts = {
            "own_records_only": "Ticked: people see only records they created (in Tasks also tasks they own, "
                                "review or help with, and their team's). Not ticked: they see all records "
                                "of these apps in their companies.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        choices = [(app.code, app.name) for app in all_apps()]
        tooltips = {app.code: app.description or app.name for app in all_apps()}
        known = {code for code, _ in choices}
        # A code saved earlier for an app that is no longer installed stays visible, so saving does not drop it.
        for code in self.instance.allowed_apps or []:
            if code not in known:
                choices.append((code, f"{code} (app not installed)"))
        field = self.fields["allowed_apps"]
        field.choices = choices
        field.widget = AppTickBoxes(choices=choices, tooltips=tooltips)
