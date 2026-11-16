"""Reports: Excel, Word and print page with company header and footer; only rows and columns the user may see."""
import io
import struct
import zlib
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory
from docx import Document
from openpyxl import load_workbook

from core.accounts.models import CompanyRole, Role
from core.masters.models import Company, Vendor
from core.reports import services as reports

User = get_user_model()
PASSWORD = "a-long-password-123"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64  # starts like a PNG, but is not a real picture
pytestmark = pytest.mark.django_db


def real_png():
    """A real 1x1 white PNG."""
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(b"\x00\xff\xff\xff")) + chunk(b"IEND", b""))


@pytest.fixture(autouse=True)
def private_folder(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path


@pytest.fixture
def acme():
    return Company.objects.create(name="Acme", code="ACME", address="1 MG Road\nPune", pan="ABCDE1234F",
                                  gstn="27ABCDE1234F1Z5")


@pytest.fixture
def globex():
    return Company.objects.create(name="Globex", code="GLOBEX")


@pytest.fixture
def vendors(acme, globex):
    Vendor.objects.create(company=acme, name="Steel Co", phone="9811111111", bank_account_number="111222333")
    Vendor.objects.create(company=acme, name="=1+1 Traders")
    Vendor.objects.create(company=globex, name="Secret Vendor")


def make_user(email, companies, **extra):
    user = User.objects.create_user(email=email, password=PASSWORD, first_name="Ravi", last_name="Kumar", **extra)
    role = Role.objects.create(name=f"role-{email}", allowed_apps=["masters"])
    for company in companies:
        CompanyRole.objects.create(user=user, company=company, role=role)
    return user


def test_indian_number_grouping():
    assert reports.indian_number(Decimal("12345678.5")) == "1,23,45,678.50"
    assert reports.indian_number(Decimal("100000")) == "1,00,000.00"
    assert reports.indian_number(1234) == "1,234"
    assert reports.indian_number(Decimal("-1234567.25")) == "-12,34,567.25"


def test_excel_has_header_filtered_rows_and_footer(client, acme, vendors):
    client.force_login(make_user("ravi@example.com", [acme]))

    response = client.get("/masters/vendors/?q=Steel&report=xlsx")

    assert response["Content-Disposition"].startswith('attachment; filename="vendors_')
    sheet = load_workbook(io.BytesIO(response.content)).active
    cells = [row for row in sheet.iter_rows(values_only=True)]
    flat = [value for row in cells for value in row if value]
    assert cells[0][0] == "Acme"
    assert "GSTN: 27ABCDE1234F1Z5" in flat and "1 MG Road" in flat
    assert "Steel Co" in flat
    assert "=1+1 Traders" not in flat and "Secret Vendor" not in flat  # search applied; other company never
    assert "Printed by Ravi Kumar on" in sheet.oddFooter.left.text
    assert sheet.oddFooter.right.text == "Page &P of &N"


def test_excel_keeps_formula_looking_names_as_text(client, acme, vendors):
    client.force_login(make_user("ravi@example.com", [acme]))

    sheet = load_workbook(io.BytesIO(client.get("/masters/vendors/?report=xlsx").content)).active

    values = [cell.value for row in sheet.iter_rows() for cell in row]
    assert "'=1+1 Traders" in values


def test_word_has_header_table_and_page_numbers(client, acme, vendors):
    client.force_login(make_user("ravi@example.com", [acme]))

    response = client.get("/masters/vendors/?report=docx")

    document = Document(io.BytesIO(response.content))
    section = document.sections[0]
    header_text = section.header.paragraphs[0].text
    table_text = [cell.text for row in document.tables[0].rows for cell in row.cells]
    footer_xml = section.footer.paragraphs[0]._p.xml
    assert "Acme" in header_text and "GSTN: 27ABCDE1234F1Z5" in header_text
    assert "Steel Co" in table_text and "Secret Vendor" not in table_text
    assert "Printed by Ravi Kumar" in section.footer.paragraphs[0].text
    assert "PAGE" in footer_xml and "NUMPAGES" in footer_xml


def test_print_page_has_header_rows_and_print_button(client, acme, vendors):
    client.force_login(make_user("ravi@example.com", [acme]))

    content = client.get("/masters/vendors/?report=print").content.decode()

    assert "Acme" in content and "GSTN: 27ABCDE1234F1Z5" in content
    assert "Steel Co" in content and "Secret Vendor" not in content
    assert "Printed by Ravi Kumar on" in content
    assert "Print or save as PDF" in content


def test_user_of_several_companies_gets_the_group_header(client, acme, globex, vendors):
    client.force_login(make_user("ravi@example.com", [acme, globex]))

    content = client.get("/masters/vendors/?report=print").content.decode()

    assert "Group ERP: all your companies" in content
    assert "Secret Vendor" in content


def test_bank_columns_are_left_out_without_permission(acme, vendors):
    ravi = make_user("ravi@example.com", [acme])
    columns = [("Name", "name"), ("Account number", "bank_account_number")]

    report = reports.make_report(ravi, "Vendors", columns, Vendor.objects.for_user(ravi), model=Vendor)

    assert report.headings == ["Name"]
    assert all("111222333" not in str(row) for row in report.rows)


def test_logo_appears_in_word_and_print(client, acme, vendors):
    acme.logo = SimpleUploadedFile("logo.png", PNG)
    acme.save()
    client.force_login(make_user("ravi@example.com", [acme]))

    print_page = client.get("/masters/vendors/?report=print").content.decode()
    report = reports.make_report(User.objects.get(), "Vendors", [("Name", "name")], [], company=acme)

    assert 'src="data:image/png;base64,' in print_page
    assert report.logo == PNG


def test_word_cuts_very_long_reports_and_says_so(acme, monkeypatch):
    monkeypatch.setattr(reports, "MAX_PAGE_ROWS", 2)
    ravi = make_user("ravi@example.com", [acme])
    rows = [Vendor(company=acme, name=f"Vendor {number}") for number in range(5)]
    report = reports.make_report(ravi, "Vendors", [("Name", "name")], rows, company=acme)

    document = Document(io.BytesIO(reports.to_docx(report)))

    assert len(document.tables[0].rows) == 3  # heading + 2
    assert "Showing the first 2 of 5 rows" in document.paragraphs[-1].text


def test_unknown_report_kind_shows_the_normal_list(client, acme, vendors):
    client.force_login(make_user("ravi@example.com", [acme]))

    response = client.get("/masters/vendors/?report=pdf")

    assert response.status_code == 200 and b"Steel Co" in response.content


def test_report_links_follow_the_filters_and_replace_themselves(client, acme, vendors):
    client.force_login(make_user("ravi@example.com", [acme]))

    page = client.get("/masters/vendors/?q=Steel").content.decode()
    table_click = client.get("/masters/vendors/?q=Steel", HTTP_HX_REQUEST="true",
                             HTTP_HX_TARGET="vendors-table").content.decode()

    assert "q=Steel&amp;report=xlsx" in page
    assert 'id="report-links" hx-swap-oob="true"' in table_click


def test_company_logo_is_checked_like_a_file(acme, globex, client):
    acme.logo = SimpleUploadedFile("logo.png", b"MZ program")
    with pytest.raises(ValidationError, match="not a real .png file"):
        acme.full_clean()

    acme.logo = SimpleUploadedFile("logo.png", PNG)
    acme.save()
    client.force_login(make_user("ravi@example.com", [acme]))
    assert client.get(acme.logo.url).status_code == 200
    client.force_login(make_user("gita@example.com", [globex]))
    assert client.get(acme.logo.url).status_code == 404


def test_unknown_kind_in_code_is_an_error(acme):
    ravi = make_user("ravi@example.com", [acme])
    request = RequestFactory().get("/")
    request.user = ravi
    report = reports.make_report(ravi, "Vendors", [("Name", "name")], [])

    with pytest.raises(ValueError):
        reports.report_response(request, report, "pdf")


def test_real_logo_is_placed_in_the_word_header(acme):
    acme.logo = SimpleUploadedFile("logo.png", real_png())
    acme.save()
    report = reports.make_report(make_user("ravi@example.com", [acme]), "Vendors", [("Name", "name")], [], company=acme)

    document = Document(io.BytesIO(reports.to_docx(report)))

    header_part = document.sections[0].header.part
    assert any("image" in rel.reltype for rel in header_part.rels.values())


def test_broken_logo_does_not_stop_the_word_report(acme):
    acme.logo = SimpleUploadedFile("logo.png", PNG)
    acme.save()
    report = reports.make_report(make_user("ravi@example.com", [acme]), "Vendors", [("Name", "name")], [], company=acme)

    document = Document(io.BytesIO(reports.to_docx(report)))

    assert "Acme" in document.sections[0].header.paragraphs[0].text
