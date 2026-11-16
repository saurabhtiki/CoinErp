"""Masters: format checks, company rules, list screens and admin, all through the access layer."""
import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile

from core.accounts.models import CompanyRole, Role
from core.masters.models import Branch, Company, Customer, Department, Employee, Vendor

User = get_user_model()
PASSWORD = "a-long-password-123"


@pytest.fixture
def acme():
    return Company.objects.create(name="Acme", code="ACME")


@pytest.fixture
def globex():
    return Company.objects.create(name="Globex", code="GLOBEX")


def make_user(email, companies, apps=("masters",), **extra):
    user = User.objects.create_user(email=email, password=PASSWORD, first_name="Ravi", **extra)
    role = Role.objects.create(name=f"role-{email}", allowed_apps=list(apps))
    for company in companies:
        CompanyRole.objects.create(user=user, company=company, role=role)
    return user


# --- Format checks ----------------------------------------------------------------


@pytest.mark.django_db
def test_valid_company_ids_pass_and_are_saved_upper_case():
    company = Company(
        name="Acme", code="acme", pan="abcde1234f", tan="ABCD12345E", gstn="27ABCDE1234F1Z5",
        cin="U12345MH2020PTC123456",
    )
    company.full_clean()
    company.save()

    assert (company.code, company.pan) == ("ACME", "ABCDE1234F")


@pytest.mark.parametrize(
    "field, bad_value, message",
    [
        ("pan", "ABCDE12345", "PAN must look like ABCDE1234F."),
        ("tan", "ABC123", "TAN must look like ABCD12345E."),
        ("gstn", "27ABCDE1234F1X5", "GSTN must look like 27ABCDE1234F1Z5."),
        ("cin", "X12345MH2020PTC123456", "CIN must look like U12345MH2020PTC123456."),
    ],
)
@pytest.mark.django_db
def test_wrong_company_id_format_is_rejected(field, bad_value, message):
    company = Company(name="Acme", code="ACME", **{field: bad_value})

    with pytest.raises(ValidationError) as error:
        company.full_clean()

    assert error.value.message_dict[field] == [message]


@pytest.mark.django_db
def test_gstn_must_contain_the_pan():
    company = Company(name="Acme", code="ACME", pan="ABCDE1234F", gstn="27ZZZZZ9999Z1Z5")

    with pytest.raises(ValidationError) as error:
        company.full_clean()

    assert "does not belong to PAN ABCDE1234F" in error.value.message_dict["gstn"][0]


@pytest.mark.django_db
def test_vendor_ifsc_and_mobile_checks(acme):
    vendor = Vendor(company=acme, name="Steel Co", bank_ifsc="HDFC1234567")
    employee = Employee(company=acme, employee_code="E1", first_name="Asha", mobile="12345")

    with pytest.raises(ValidationError, match="IFSC must look like HDFC0001234"):
        vendor.full_clean()
    with pytest.raises(ValidationError, match="Mobile must be 10 digits"):
        employee.full_clean()


@pytest.mark.django_db
def test_photo_must_be_jpg_or_png(acme):
    employee = Employee(
        company=acme, employee_code="E1", first_name="Asha",
        profile_photo=SimpleUploadedFile("cv.pdf", b"%PDF", content_type="application/pdf"),
    )

    with pytest.raises(ValidationError, match="Photo must be a JPG or PNG file"):
        employee.full_clean()


# --- Company rules ----------------------------------------------------------------


@pytest.mark.django_db
def test_same_code_allowed_in_two_companies_but_not_twice_in_one(acme, globex):
    Branch.objects.create(company=acme, name="Pune", code="PUN")
    Branch.objects.create(company=globex, name="Pune", code="PUN")

    with pytest.raises(ValidationError):
        Branch(company=acme, name="Pune 2", code="pun").full_clean()


@pytest.mark.django_db
def test_employee_code_unique_per_company(acme, globex):
    Employee.objects.create(company=acme, employee_code="E1", first_name="Asha")
    Employee.objects.create(company=globex, employee_code="E1", first_name="Bina")

    with pytest.raises(ValidationError):
        Employee(company=acme, employee_code="E1", first_name="Chetan").full_clean()


@pytest.mark.django_db
def test_employee_cannot_use_branch_or_manager_of_other_company(acme, globex):
    globex_branch = Branch.objects.create(company=globex, name="Delhi", code="DEL")
    globex_boss = Employee.objects.create(company=globex, employee_code="B1", first_name="Boss")
    employee = Employee(company=acme, employee_code="E1", first_name="Asha", branch=globex_branch, reports_to=globex_boss)

    with pytest.raises(ValidationError) as error:
        employee.full_clean()

    assert set(error.value.message_dict) >= {"branch", "reports_to"}


@pytest.mark.django_db
def test_employee_cannot_report_to_self(acme):
    employee = Employee.objects.create(company=acme, employee_code="E1", first_name="Asha")
    employee.reports_to = employee

    with pytest.raises(ValidationError, match="cannot report to themselves"):
        employee.full_clean()


@pytest.mark.django_db
def test_one_login_can_be_employee_in_two_companies_but_once_per_company(acme, globex):
    ravi = make_user("ravi@example.com", [acme, globex])
    Employee.objects.create(company=acme, employee_code="E42", first_name="Ravi", designation="Manager", user=ravi)
    Employee.objects.create(company=globex, employee_code="E07", first_name="Ravi", designation="Admin", user=ravi)

    assert ravi.employees.count() == 2
    with pytest.raises(ValidationError):
        Employee(company=acme, employee_code="E43", first_name="Ravi", user=ravi).full_clean()


# --- List screens -----------------------------------------------------------------


@pytest.mark.django_db
def test_list_shows_only_own_company_rows(client, acme, globex):
    client.force_login(make_user("ravi@example.com", [acme]))
    Branch.objects.create(company=acme, name="Pune", code="PUN")
    Branch.objects.create(company=globex, name="Delhi", code="DEL")

    response = client.get("/masters/branches/")

    assert response.status_code == 200
    assert b"Pune" in response.content
    assert b"Delhi" not in response.content


@pytest.mark.django_db
def test_company_list_shows_only_assigned_companies(client, acme, globex):
    client.force_login(make_user("ravi@example.com", [acme]))

    content = client.get("/masters/companies/").content

    assert b"Acme" in content
    assert b"Globex" not in content


@pytest.mark.django_db
def test_every_master_list_opens(client, acme):
    client.force_login(make_user("ravi@example.com", [acme]))
    for slug in ["companies", "branches", "departments", "cost-centres", "employees", "vendors", "customers"]:
        assert client.get(f"/masters/{slug}/").status_code == 200, slug


@pytest.mark.django_db
def test_user_without_masters_role_gets_403(client, acme):
    client.force_login(make_user("ravi@example.com", [acme], apps=["travel"]))

    assert client.get("/masters/branches/").status_code == 403


@pytest.mark.django_db
def test_unknown_master_gives_404(client, acme):
    client.force_login(make_user("ravi@example.com", [acme]))

    assert client.get("/masters/spaceships/").status_code == 404


@pytest.mark.django_db
def test_table_click_returns_only_the_table(client, acme):
    client.force_login(make_user("ravi@example.com", [acme]))
    Department.objects.create(company=acme, name="Accounts", code="ACC")

    response = client.get(
        "/masters/departments/?sort=-name", headers={"HX-Request": "true", "HX-Target": "departments-table"}
    )

    assert b"Accounts" in response.content
    assert b"<html" not in response.content


@pytest.mark.django_db
def test_csv_download_has_only_own_rows(client, acme, globex):
    client.force_login(make_user("ravi@example.com", [acme]))
    Customer.objects.create(company=acme, name="Mehta Traders")
    Customer.objects.create(company=globex, name="Secret Buyer")

    response = client.get("/masters/customers/?format=csv")
    content = b"".join(response.streaming_content) if response.streaming else response.content

    assert b"Mehta Traders" in content
    assert b"Secret Buyer" not in content


# --- Admin ------------------------------------------------------------------------


def staff_user(client, companies, apps=("masters",)):
    user = make_user("staff@example.com", companies, apps=apps, is_staff=True)
    client.force_login(user)
    return user


@pytest.mark.django_db
def test_admin_lists_only_own_company_rows(client, acme, globex):
    staff_user(client, [acme])
    Branch.objects.create(company=acme, name="Pune", code="PUN")
    Branch.objects.create(company=globex, name="Delhi", code="DEL")

    content = client.get("/admin/masters/branch/").content

    assert b"Pune" in content
    assert b"Delhi" not in content


@pytest.mark.django_db
def test_admin_hides_other_company_record_and_company_choice(client, acme, globex):
    staff_user(client, [acme])
    delhi = Branch.objects.create(company=globex, name="Delhi", code="DEL")

    add_page = client.get("/admin/masters/branch/add/").content

    assert b"Acme" in add_page
    assert b"Globex" not in add_page
    assert client.get(f"/admin/masters/branch/{delhi.pk}/change/").status_code == 302  # "not found" redirect


@pytest.mark.django_db
def test_admin_fills_created_by(client, acme):
    user = staff_user(client, [acme])

    client.post("/admin/masters/department/add/", {"company": acme.pk, "name": "Sales", "code": "sal", "is_active": "on"})

    department = Department.objects.get()
    assert (department.code, department.created_by) == ("SAL", user)


@pytest.mark.django_db
def test_staff_without_masters_role_cannot_use_masters_admin(client, acme):
    staff_user(client, [acme], apps=["travel"])

    assert client.get("/admin/masters/branch/").status_code == 403


@pytest.mark.django_db
def test_bank_details_hidden_without_permission(client, acme):
    staff_user(client, [acme])
    vendor = Vendor.objects.create(company=acme, name="Steel Co", bank_account_number="1234567890")

    content = client.get(f"/admin/masters/vendor/{vendor.pk}/change/").content

    assert b"bank_account_number" not in content
    assert b"1234567890" not in content


@pytest.mark.django_db
def test_bank_details_shown_with_permission(client, acme):
    user = staff_user(client, [acme])
    user.user_permissions.add(Permission.objects.get(codename="view_bank_details"))
    vendor = Vendor.objects.create(company=acme, name="Steel Co", bank_account_number="1234567890")

    content = client.get(f"/admin/masters/vendor/{vendor.pk}/change/").content

    assert b"1234567890" in content


@pytest.mark.django_db
def test_employee_login_dropdown_lists_only_colleagues(client, acme, globex):
    staff_user(client, [acme])
    make_user("colleague@example.com", [acme], apps=(), last_name="Colleague")
    make_user("outsider@example.com", [globex], apps=(), last_name="Outsider")

    content = client.get("/admin/masters/employee/add/").content

    assert b"Ravi Colleague" in content
    assert b"Ravi Outsider" not in content
