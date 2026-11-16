"""Audit trail: every change is recorded, and history follows the same who-sees-what rules."""
import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission

from core.accounts.models import CompanyRole, Role
from core.masters.models import Company, Vendor
from tests.access_demo.models import Note

User = get_user_model()
PASSWORD = "a-long-password-123"


@pytest.fixture
def acme():
    return Company.objects.create(name="Acme", code="ACME")


@pytest.fixture
def globex():
    return Company.objects.create(name="Globex", code="GLOBEX")


@pytest.fixture
def steel(acme):
    return Vendor.objects.create(company=acme, name="Steel Co", phone="9811111111", bank_account_number="111222333")


def make_user(email, companies, apps=("masters",), **extra):
    user = User.objects.create_user(email=email, password=PASSWORD, first_name="Ravi", **extra)
    role = Role.objects.create(name=f"role-{email}", allowed_apps=list(apps))
    for company in companies:
        CompanyRole.objects.create(user=user, company=company, role=role)
    return user


def history_url(record):
    return f"/history/{record._meta.app_label}/{record._meta.model_name}/{record.pk}/"


@pytest.mark.django_db
def test_admin_change_is_recorded_with_who_and_old_and_new_value(client, acme, steel):
    ravi = make_user("ravi@example.com", [acme], is_staff=True)
    client.force_login(ravi)

    client.post(
        f"/admin/masters/vendor/{steel.pk}/change/",
        {"company": acme.pk, "name": "Steel Co", "phone": "9922222222", "is_active": "on"},
    )

    latest = steel.history.first()
    assert (latest.history_type, latest.history_user) == ("~", ravi)
    page = client.get(history_url(steel)).content.decode()
    assert "Ravi" in page
    assert "Phone:" in page and "9811111111" in page and "9922222222" in page


@pytest.mark.django_db
def test_every_business_record_keeps_history_automatically(acme):
    note = Note.objects.create(company=acme, title="First")
    note.title = "Second"
    note.save()

    assert [version.title for version in note.history.all()] == ["Second", "First"]


@pytest.mark.django_db
def test_history_of_another_companys_record_is_not_found(client, globex, steel):
    client.force_login(make_user("gita@example.com", [globex]))

    assert client.get(history_url(steel)).status_code == 404


@pytest.mark.django_db
def test_history_needs_the_app_and_a_login(client, acme, steel):
    assert client.get(history_url(steel)).status_code == 302  # to login

    client.force_login(make_user("tom@example.com", [acme], apps=["travel"]))
    assert client.get(history_url(steel)).status_code == 404


@pytest.mark.django_db
def test_bank_details_are_hidden_in_history_without_permission(client, acme, steel):
    steel.bank_account_number = "999888777"
    steel.save()
    ravi = make_user("ravi@example.com", [acme])
    client.force_login(ravi)

    page = client.get(history_url(steel)).content.decode()
    assert "999888777" not in page and "111222333" not in page
    assert "No changes you can see." in page

    ravi.user_permissions.add(Permission.objects.get(codename="view_bank_details"))
    client.force_login(User.objects.get(pk=ravi.pk))  # fresh user, fresh permission cache
    assert "999888777" in client.get(history_url(steel)).content.decode()


@pytest.mark.django_db
def test_user_history_never_stores_the_password(acme):
    user = make_user("ravi@example.com", [acme])
    user.set_password("another-long-password-1")
    user.save()

    field_names = {field.name for field in User.history.model._meta.fields}
    assert "password" not in field_names
    assert "last_login" not in field_names
    assert user.history.count() == 2


@pytest.mark.django_db
def test_company_roles_and_roles_keep_history(acme):
    user = make_user("ravi@example.com", [acme])
    link = CompanyRole.objects.get(user=user)
    link_id = link.pk
    link.delete()

    assert CompanyRole.history.filter(id=link_id, history_type="-").exists()
    assert Role.history.filter(name="role-ravi@example.com").exists()


@pytest.mark.django_db
def test_only_tracked_and_visible_kinds_of_record_have_a_history_page(client, acme):
    ravi = make_user("ravi@example.com", [acme])
    client.force_login(ravi)

    assert client.get(f"/history/accounts/user/{ravi.pk}/").status_code == 404  # users: admin only
    assert client.get("/history/nope/thing/1/").status_code == 404


@pytest.mark.django_db
def test_masters_list_has_a_history_link_for_everyone(client, acme, steel):
    client.force_login(make_user("ravi@example.com", [acme]))

    content = client.get("/masters/vendors/").content.decode()

    assert f'href="{history_url(steel)}"' in content


# --- Admin history pages ------------------------------------------------------------


@pytest.mark.django_db
def test_admin_old_version_of_another_companys_record_is_refused(client, acme, globex, steel):
    version = steel.history.first()
    client.force_login(make_user("gita@example.com", [globex], is_staff=True))

    assert client.get(f"/admin/masters/vendor/{steel.pk}/history/{version.history_id}/").status_code == 403
    assert client.get(f"/admin/masters/vendor/{steel.pk}/history/").status_code == 403


@pytest.mark.django_db
def test_admin_history_shows_changes_but_not_bank_details(client, acme, steel):
    steel.phone = "9922222222"
    steel.bank_account_number = "999888777"
    steel.save()
    client.force_login(make_user("ravi@example.com", [acme], is_staff=True))

    content = client.get(f"/admin/masters/vendor/{steel.pk}/history/").content.decode()

    assert "9922222222" in content
    assert "999888777" not in content


@pytest.mark.django_db
def test_admin_old_version_page_opens_for_own_company(client, acme, steel):
    version = steel.history.first()
    client.force_login(make_user("ravi@example.com", [acme], is_staff=True))

    response = client.get(f"/admin/masters/vendor/{steel.pk}/history/{version.history_id}/")

    assert response.status_code == 200
    assert b"Revert" not in response.content  # view only


@pytest.mark.django_db
def test_admin_user_history_pages_open_without_the_password(client, acme):
    staff = make_user("admin@example.com", [acme], is_staff=True)
    staff.user_permissions.add(Permission.objects.get(codename="view_user"))
    ravi = make_user("ravi@example.com", [acme])
    ravi.first_name = "Ravindra"
    ravi.save()
    client.force_login(staff)

    listing = client.get(f"/admin/accounts/user/{ravi.pk}/history/")
    version = client.get(f"/admin/accounts/user/{ravi.pk}/history/{ravi.history.last().history_id}/")

    assert listing.status_code == 200 and b"Ravindra" in listing.content
    assert version.status_code == 200


@pytest.mark.django_db
def test_history_page_looks_up_linked_records_once(client, acme, django_assert_max_num_queries):
    from core.masters.models import Branch, Employee

    branches = [Branch.objects.create(company=acme, name=f"Branch {number}", code=f"B{number}") for number in range(6)]
    employee = Employee.objects.create(company=acme, employee_code="E1", first_name="Asha")
    for branch in branches:  # 6 changes of a linked record
        employee.branch = branch
        employee.save()
    client.force_login(make_user("ravi@example.com", [acme]))

    with django_assert_max_num_queries(12):
        page = client.get(history_url(employee)).content.decode()

    assert "Branch 0 (B0)" in page and "Branch 5 (B5)" in page
