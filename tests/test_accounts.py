import re

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.urls import reverse
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice

from core.accounts.models import CompanyRole, Role
from core.masters.models import Company

PASSWORD = "a-long-password-123"
User = get_user_model()


def make_user(email="ravi@example.com", **extra):
    return User.objects.create_user(email=email, password=PASSWORD, first_name="Ravi", **extra)


def current_code(device):
    return f"{totp(device.bin_key, step=device.step, t0=device.t0, digits=device.digits):06d}"


def login(client, email, password=PASSWORD):
    return client.post(reverse("login"), {"username": email, "password": password})


# --- Login with email -------------------------------------------------------------


@pytest.mark.django_db
def test_user_logs_in_with_email_any_case(client):
    make_user()

    response = login(client, "Ravi@Example.com")

    assert response.status_code == 302
    assert response.url == "/"


@pytest.mark.django_db
def test_email_is_saved_lower_case():
    user = make_user(email="Ravi@Example.COM")

    assert user.email == "ravi@example.com"


@pytest.mark.django_db
def test_wrong_password_shows_error(client):
    make_user()

    response = login(client, "ravi@example.com", "wrong-password")

    assert response.status_code == 200
    assert b"Please enter a correct email address and password" in response.content


def test_there_is_no_public_signup_page(client):
    assert client.get("/accounts/signup/").status_code == 404


# --- Lockout ----------------------------------------------------------------------


@pytest.mark.django_db
def test_account_locks_after_five_wrong_passwords(client):
    make_user()
    for _ in range(5):
        login(client, "ravi@example.com", "wrong-password")

    response = login(client, "ravi@example.com")  # right password, but locked

    assert response.status_code == 429
    assert b"locked for 30 minutes" in response.content


@pytest.mark.django_db
def test_changing_email_case_does_not_dodge_lock(client):
    make_user()
    for _ in range(5):
        login(client, "ravi@example.com", "wrong-password")

    assert login(client, "RAVI@example.com").status_code == 429


@pytest.mark.django_db
def test_lock_affects_only_that_account(client):
    make_user()
    make_user(email="sita@example.com")
    for _ in range(5):
        login(client, "ravi@example.com", "wrong-password")

    assert login(client, "sita@example.com").status_code == 302


# --- 2FA --------------------------------------------------------------------------


@pytest.mark.django_db
def test_user_without_2fa_role_goes_straight_in(client):
    client.force_login(make_user())

    assert client.get(reverse("core:home")).status_code == 200


@pytest.mark.django_db
def test_role_with_2fa_sends_user_to_setup(client):
    user = make_user()
    CompanyRole.objects.create(
        user=user,
        company=Company.objects.create(name="Acme", code="ACME"),
        role=Role.objects.create(name="Finance", requires_2fa=True),
    )
    client.force_login(user)

    response = client.get(reverse("core:home"))

    assert response.status_code == 302
    assert response.url == reverse("accounts:otp_setup")


@pytest.mark.django_db
def test_superuser_always_needs_2fa(client):
    admin_user = User.objects.create_superuser(email="boss@example.com", password=PASSWORD)
    client.force_login(admin_user)

    assert client.get("/admin/").url == reverse("accounts:otp_setup")


@pytest.mark.django_db
def test_htmx_request_gets_client_redirect_to_2fa(client):
    admin_user = User.objects.create_superuser(email="boss@example.com", password=PASSWORD)
    client.force_login(admin_user)

    response = client.get(reverse("core:home"), headers={"HX-Request": "true"})

    assert response.headers["HX-Redirect"] == reverse("accounts:otp_setup")


@pytest.mark.django_db
def test_2fa_setup_with_right_code_lets_user_in(client):
    admin_user = User.objects.create_superuser(email="boss@example.com", password=PASSWORD)
    client.force_login(admin_user)
    page = client.get(reverse("accounts:otp_setup"))
    assert b"<svg" in page.content
    device = TOTPDevice.objects.get(user=admin_user, confirmed=False)

    response = client.post(reverse("accounts:otp_setup"), {"token": current_code(device)})

    assert response.status_code == 302
    device.refresh_from_db()
    assert device.confirmed
    assert client.get(reverse("core:home")).status_code == 200


@pytest.mark.django_db
def test_2fa_setup_with_wrong_code_shows_error(client):
    admin_user = User.objects.create_superuser(email="boss@example.com", password=PASSWORD)
    client.force_login(admin_user)
    client.get(reverse("accounts:otp_setup"))

    response = client.post(reverse("accounts:otp_setup"), {"token": "000000"})

    assert b"That code is wrong or expired" in response.content
    assert not TOTPDevice.objects.filter(user=admin_user, confirmed=True).exists()


@pytest.mark.django_db
def test_user_with_device_must_enter_code_after_login(client):
    admin_user = User.objects.create_superuser(email="boss@example.com", password=PASSWORD)
    device = TOTPDevice.objects.create(user=admin_user, name="phone", confirmed=True)
    login(client, "boss@example.com")

    assert client.get(reverse("core:home")).url == reverse("accounts:otp_verify")

    client.post(reverse("accounts:otp_verify"), {"token": current_code(device)})

    assert client.get(reverse("core:home")).status_code == 200


@pytest.mark.django_db
def test_wrong_login_code_keeps_user_out(client):
    admin_user = User.objects.create_superuser(email="boss@example.com", password=PASSWORD)
    TOTPDevice.objects.create(user=admin_user, name="phone", confirmed=True)
    login(client, "boss@example.com")

    response = client.post(reverse("accounts:otp_verify"), {"token": "000000"})

    assert b"That code is wrong or expired" in response.content
    assert client.get(reverse("core:home")).status_code == 302


@pytest.mark.django_db
def test_admin_sets_company_roles_on_user_page(client):
    verified_admin(client)
    ravi = make_user()
    acme = Company.objects.create(name="Acme", code="ACME")
    manager = Role.objects.create(name="Manager")
    page = client.get(reverse("admin:accounts_user_change", args=[ravi.pk]))
    data = {
        key: value for key, value in page.context["adminform"].form.initial.items()
        if key in {"email", "first_name", "last_name"}
    }
    data.update({
        "is_active": "on",
        "company_roles-TOTAL_FORMS": "1", "company_roles-INITIAL_FORMS": "0",
        "company_roles-0-company": acme.pk, "company_roles-0-role": manager.pk,
        "last_login_0": "", "date_joined_0": "",
    })

    client.post(reverse("admin:accounts_user_change", args=[ravi.pk]), data)

    assert list(ravi.company_roles.values_list("company__code", "role__name")) == [("ACME", "Manager")]


# --- Admin and invites ------------------------------------------------------------


def verified_admin(client):
    admin_user = User.objects.create_superuser(email="boss@example.com", password=PASSWORD)
    device = TOTPDevice.objects.create(user=admin_user, name="phone", confirmed=True)
    login(client, "boss@example.com")
    client.post(reverse("accounts:otp_verify"), {"token": current_code(device)})
    return admin_user


@pytest.mark.django_db
def test_admin_adds_user_and_invite_email_lets_them_set_password(client):
    verified_admin(client)

    client.post(
        reverse("admin:accounts_user_add"),
        {"email": "new@example.com", "first_name": "Asha", "last_name": "K", "is_external": ""},
    )

    new_user = User.objects.get(email="new@example.com")
    assert not new_user.has_usable_password()
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["new@example.com"]
    link = re.search(r"http://testserver(\S+)", mail.outbox[0].body).group(1)

    client.post(reverse("logout"))
    set_password_page = client.get(link, follow=True)
    client.post(
        set_password_page.redirect_chain[-1][0],
        {"new_password1": "Fresh-Pass-2026!", "new_password2": "Fresh-Pass-2026!"},
    )

    assert login(client, "new@example.com", "Fresh-Pass-2026!").status_code == 302


@pytest.mark.django_db
def test_external_user_cannot_open_admin_even_if_staff(client):
    client.force_login(make_user(is_external=True, is_staff=True))

    response = client.get("/admin/")

    assert response.status_code == 302
    assert response.url.startswith("/admin/login/")
