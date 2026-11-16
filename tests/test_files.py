"""Private files: who can upload, download and delete, and which files are refused."""
import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile

from core.accounts.models import CompanyRole, Role
from core.files.models import FileAttachment
from core.masters.models import Company, Employee, Vendor

User = get_user_model()
PASSWORD = "a-long-password-123"
PDF = b"%PDF-1.4 test file"
PNG = b"\x89PNG\r\n\x1a\n test image"


@pytest.fixture(autouse=True)
def private_folder(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path


@pytest.fixture
def acme():
    return Company.objects.create(name="Acme", code="ACME")


@pytest.fixture
def globex():
    return Company.objects.create(name="Globex", code="GLOBEX")


@pytest.fixture
def steel(acme):
    return Vendor.objects.create(company=acme, name="Steel Co")


def make_user(email, companies, apps=("masters",), **extra):
    user = User.objects.create_user(email=email, password=PASSWORD, first_name="Ravi", **extra)
    role = Role.objects.create(name=f"role-{email}", allowed_apps=list(apps))
    for company in companies:
        CompanyRole.objects.create(user=user, company=company, role=role)
    return user


def files_url(record):
    return f"/files/{record._meta.app_label}/{record._meta.model_name}/{record.pk}/"


def upload(client, record, name="gst.pdf", content=PDF, **headers):
    return client.post(files_url(record), {"file": SimpleUploadedFile(name, content)}, **headers)


@pytest.mark.django_db
def test_upload_then_download_in_own_company(client, acme, steel):
    client.force_login(make_user("ravi@example.com", [acme]))

    assert upload(client, steel).status_code == 302
    attachment = FileAttachment.objects.get()
    response = client.get(attachment.file.url)

    assert attachment.original_name == "gst.pdf"
    assert attachment.file.url.startswith("/files/private/attachments/")
    assert "gst" not in attachment.file.name  # stored under a random name
    assert b"".join(response.streaming_content) == PDF
    assert response["Content-Disposition"].startswith("inline")
    assert response["X-Content-Type-Options"] == "nosniff"
    assert response["Content-Security-Policy"] == "sandbox"


@pytest.mark.django_db
def test_other_company_cannot_see_list_upload_or_download(client, acme, globex, steel):
    client.force_login(make_user("ravi@example.com", [acme]))
    upload(client, steel)
    attachment = FileAttachment.objects.get()

    client.force_login(make_user("gita@example.com", [globex]))

    assert client.get(attachment.file.url).status_code == 404
    assert client.get(files_url(steel)).status_code == 404
    assert upload(client, steel).status_code == 404
    assert FileAttachment.objects.count() == 1


@pytest.mark.django_db
def test_files_need_a_login(client, acme, steel):
    assert client.get(files_url(steel)).status_code == 302
    assert client.get("/files/private/attachments/x.pdf").status_code == 302


@pytest.mark.parametrize(
    "name, content, message",
    [
        ("tool.exe", b"MZ program", "This type of file is not allowed."),
        ("fake.pdf", b"MZ program", "This file is not a real .pdf file."),
        ("fake.xlsx", PDF, "This file is not a real .xlsx file."),
        ("big.pdf", PDF + b"0" * (10 * 1024 * 1024), "File is too big"),
    ],
)
@pytest.mark.django_db
def test_wrong_files_are_refused_with_a_clear_message(client, acme, steel, name, content, message):
    client.force_login(make_user("ravi@example.com", [acme]))

    response = upload(client, steel, name=name, content=content, HTTP_HX_REQUEST="true")

    assert message in response.content.decode()
    assert b'id="files-panel"' in response.content and b"<html" not in response.content
    assert not FileAttachment.objects.exists()


@pytest.mark.django_db
def test_excel_and_csv_are_downloaded_not_opened(client, acme, steel):
    client.force_login(make_user("ravi@example.com", [acme]))
    upload(client, steel, name="rates.xlsx", content=b"PK\x03\x04 sheet")
    upload(client, steel, name="list.csv", content=b"name,amount\nSteel,10\n")

    for attachment in FileAttachment.objects.all():
        response = client.get(attachment.file.url)
        assert response["Content-Disposition"].startswith("attachment")


@pytest.mark.django_db
def test_uploader_and_staff_can_delete_others_cannot(client, acme, steel):
    ravi = make_user("ravi@example.com", [acme])
    client.force_login(ravi)
    upload(client, steel)
    attachment = FileAttachment.objects.get()
    delete_url = f"/files/attachments/{attachment.pk}/delete/"

    client.force_login(make_user("asha@example.com", [acme]))
    assert client.post(delete_url).status_code == 403

    client.force_login(make_user("boss@example.com", [acme], is_staff=True))
    assert client.post(delete_url, HTTP_HX_REQUEST="true").status_code == 200

    attachment.refresh_from_db()
    assert attachment.is_deleted and attachment.deleted_by.email == "boss@example.com"
    assert attachment.history.first().is_deleted  # the delete shows in history

    client.force_login(ravi)
    assert client.get(attachment.file.url).status_code == 404  # hidden, though still on disk
    assert attachment.file.storage.exists(attachment.file.name)


@pytest.mark.django_db
def test_uploader_can_delete_own_file(client, acme, steel):
    client.force_login(make_user("ravi@example.com", [acme]))
    upload(client, steel)
    attachment = FileAttachment.objects.get()

    response = client.post(f"/files/attachments/{attachment.pk}/delete/", HTTP_HX_REQUEST="true")

    assert b"No files yet" in response.content


@pytest.mark.django_db
def test_files_page_lists_only_this_records_files(client, acme, steel):
    other = Vendor.objects.create(company=acme, name="Other Co")
    client.force_login(make_user("ravi@example.com", [acme]))
    upload(client, steel, name="steel.pdf")
    upload(client, other, name="other.pdf")

    content = client.get(files_url(steel)).content.decode()

    assert "steel.pdf" in content and "other.pdf" not in content


@pytest.mark.django_db
def test_employee_photo_opens_only_for_the_employees_company(client, acme, globex):
    employee = Employee(company=acme, employee_code="E1", first_name="Asha")
    employee.profile_photo = SimpleUploadedFile("asha.png", PNG)
    employee.full_clean()
    employee.save()

    client.force_login(make_user("ravi@example.com", [acme]))
    assert employee.profile_photo.url.startswith("/files/private/employees/photos/")
    assert client.get(employee.profile_photo.url).status_code == 200

    client.force_login(make_user("gita@example.com", [globex]))
    assert client.get(employee.profile_photo.url).status_code == 404


@pytest.mark.django_db
def test_fake_photo_is_refused(acme):
    employee = Employee(company=acme, employee_code="E1", first_name="Asha")
    employee.profile_photo = SimpleUploadedFile("asha.png", b"MZ program")

    with pytest.raises(Exception, match="not a real .png file"):
        employee.full_clean()


@pytest.mark.django_db
def test_unknown_or_sneaky_paths_are_not_found(client, acme):
    client.force_login(make_user("ravi@example.com", [acme]))

    assert client.get("/files/private/../../manage.py").status_code == 404
    assert client.get("/files/private/attachments/nothing.pdf").status_code == 404


@pytest.mark.django_db
def test_file_missing_on_disk_gives_a_clear_not_found(client, acme, steel):
    client.force_login(make_user("ravi@example.com", [acme]))
    upload(client, steel)
    attachment = FileAttachment.objects.get()
    attachment.file.storage.delete(attachment.file.name)

    assert client.get(attachment.file.url).status_code == 404


@pytest.mark.django_db
def test_masters_list_has_a_files_link(client, acme, steel):
    client.force_login(make_user("ravi@example.com", [acme]))

    assert f'href="{files_url(steel)}"' in client.get("/masters/vendors/").content.decode()
