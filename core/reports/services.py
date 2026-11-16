"""Report helpers: one report, three formats (Excel, Word, printable page), same header and footer.

    report = make_report(request.user, "Vendors", [("Name", "name"), ("PAN", "pan")], vendors,
                         company=acme, model=Vendor)
    return report_response(request, report, "xlsx")   # or "docx" or "print"

Header: company name, address, GSTN (and logo in Word and print). Footer: "Printed by Ravi on
16-11-2026 14:05, page 1 of 3". Columns the user may not see (e.g. bank details) are left out.
Rows must already be filtered through the access layer (e.g. Model.objects.for_user(user)).
PDF: print the page and choose "Save as PDF" (server PDFs come later).
"""
import base64
import io
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.text import slugify
from django_datatable.datatable import formula_safe
from docx import Document
from docx.enum.section import WD_ORIENT
from docx.image.exceptions import InvalidImageStreamError, UnexpectedEndOfFileError, UnrecognizedImageError
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from core.access.services import hidden_fields

logger = logging.getLogger(__name__)

KINDS = {
    "xlsx": "Excel",
    "docx": "Word",
    "print": "Print",
}
MAX_PAGE_ROWS = 2000  # Word and print get slow beyond this; Excel always has every row
XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@dataclass
class Report:
    title: str
    headings: list
    rows: list  # plain values: text, numbers, dates
    printed_by: str
    printed_at: datetime
    company: object = None  # masters.Company, or None for "all your companies"
    total_rows: int = 0
    logo: bytes = field(default=b"", repr=False)
    logo_type: str = ""

    @property
    def company_name(self):
        return self.company.name if self.company else "Group ERP: all your companies"

    @property
    def company_lines(self):
        """Address and tax ID lines under the company name."""
        if not self.company:
            return []
        lines = [line.strip() for line in self.company.address.splitlines() if line.strip()]
        if self.company.gstn:
            lines.append(f"GSTN: {self.company.gstn}")
        return lines

    @property
    def footer_text(self):
        return f"Printed by {self.printed_by} on {timezone.localtime(self.printed_at):%d-%m-%Y %H:%M}"

    @property
    def logo_data_url(self):
        if not self.logo:
            return ""
        return f"data:{self.logo_type};base64,{base64.b64encode(self.logo).decode()}"

    def limited_rows(self):
        return self.rows[:MAX_PAGE_ROWS]

    @property
    def is_cut(self):
        return len(self.rows) > MAX_PAGE_ROWS


def _read_logo(company):
    """(bytes, content type) of the company logo, or empty if there is none or it is missing on disk."""
    if not company or not company.logo:
        return b"", ""
    try:
        with company.logo.open("rb") as handle:
            data = handle.read()
    except FileNotFoundError:
        logger.warning("Logo of company %s is missing on disk", company.pk)
        return b"", ""
    return data, "image/png" if data.startswith(b"\x89PNG") else "image/jpeg"


def _value_of(row, getter):
    return getter(row) if callable(getter) else getattr(row, getter)


def make_report(user, title, columns, rows, company=None, model=None):
    """Build a report. `columns` = [(heading, field name or function of the row)]."""
    hidden = hidden_fields(model, user) if model else set()
    shown = [(heading, getter) for heading, getter in columns if getter not in hidden]
    data = [[_value_of(row, getter) for _, getter in shown] for row in rows]
    logo, logo_type = _read_logo(company)
    return Report(
        title=title,
        headings=[heading for heading, _ in shown],
        rows=data,
        printed_by=user.get_full_name() or user.email,
        printed_at=timezone.now(),
        company=company,
        total_rows=len(data),
        logo=logo,
        logo_type=logo_type,
    )


def as_text(value):
    """How a value reads in Word and on the print page. Example: Decimal("125000.5") -> "1,25,000.50"."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, datetime):
        return f"{timezone.localtime(value):%d-%m-%Y %H:%M}"
    if isinstance(value, date):
        return f"{value:%d-%m-%Y}"
    if isinstance(value, (Decimal, int, float)) and not isinstance(value, bool):
        return indian_number(value)
    return str(value)


def indian_number(value):
    """Indian digit grouping. Example: 12345678.5 -> "1,23,45,678.50"; 42 -> "42"."""
    is_whole = isinstance(value, int)
    text = f"{abs(value):.0f}" if is_whole else f"{abs(Decimal(str(value))):.2f}"
    whole, _, fraction = text.partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        whole = ",".join([head, *groups, tail]) if head else ",".join([*groups, tail])
    sign = "-" if value < 0 else ""
    return f"{sign}{whole}.{fraction}" if fraction else f"{sign}{whole}"


# --- Excel -----------------------------------------------------------------------------


def to_excel(report):
    """Excel file (bytes): header lines, a bold heading row with filters, every row. Numbers stay numbers."""
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = (slugify(report.title) or "report")[:31]
    sheet.append([report.company_name])
    sheet["A1"].font = Font(bold=True, size=14)
    for line in report.company_lines:
        sheet.append([line])
    sheet.append([report.title])
    sheet.cell(row=sheet.max_row, column=1).font = Font(bold=True, size=12)
    sheet.append([])
    sheet.append(report.headings)
    heading_row = sheet.max_row
    for cell in sheet[heading_row]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="E5E7EB")
    for row in report.rows:
        sheet.append([_excel_cell(value) for value in row])
    for column_index, heading in enumerate(report.headings, start=1):
        letter = get_column_letter(column_index)
        longest = max([len(heading), *(len(as_text(row[column_index - 1])) for row in report.rows[:500])])
        sheet.column_dimensions[letter].width = min(max(longest + 2, 8), 50)
        for row in sheet.iter_rows(min_row=heading_row + 1, min_col=column_index, max_col=column_index):
            cell = row[0]
            if isinstance(cell.value, (date, datetime)):
                cell.number_format = "DD-MM-YYYY"
            elif isinstance(cell.value, float | Decimal):
                cell.number_format = "#,##0.00"
    last_column = get_column_letter(max(len(report.headings), 1))
    sheet.auto_filter.ref = f"A{heading_row}:{last_column}{sheet.max_row}"
    sheet.freeze_panes = f"A{heading_row + 1}"
    sheet.print_title_rows = f"{heading_row}:{heading_row}"
    sheet.oddFooter.left.text = report.footer_text
    sheet.oddFooter.right.text = "Page &P of &N"
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def _excel_cell(value):
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, datetime):
        return timezone.localtime(value).replace(tzinfo=None)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, str):
        return formula_safe(value)  # a name like "=1+1" stays text
    return value


# --- Word ------------------------------------------------------------------------------


def _add_field(paragraph, code):
    """A Word field such as PAGE or NUMPAGES (filled in by Word when the file opens)."""
    field_element = OxmlElement("w:fldSimple")
    field_element.set(qn("w:instr"), code)
    run = OxmlElement("w:r")
    text = OxmlElement("w:t")
    text.text = "1"
    run.append(text)
    field_element.append(run)
    paragraph._p.append(field_element)


def to_docx(report):
    """Word file (bytes): logo and company in the page header, a table, page numbers in the footer."""
    document = Document()
    section = document.sections[0]
    if len(report.headings) > 5:
        section.orientation = WD_ORIENT.LANDSCAPE
        section.page_width, section.page_height = section.page_height, section.page_width
    for margin in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
        setattr(section, margin, Cm(1.5))

    header = section.header.paragraphs[0]
    if report.logo:
        try:
            header.add_run().add_picture(io.BytesIO(report.logo), height=Cm(1.4))
            header.add_run("\n")
        except (InvalidImageStreamError, UnexpectedEndOfFileError, UnrecognizedImageError) as error:
            logger.warning("Company logo could not be put in the Word report: %s", error)
    header.add_run(report.company_name).bold = True
    for line in report.company_lines:
        header.add_run("\n" + line).font.size = Pt(8)

    document.add_heading(report.title, level=1)
    table = document.add_table(rows=1, cols=max(len(report.headings), 1))
    table.style = "Table Grid"
    for cell, heading in zip(table.rows[0].cells, report.headings, strict=False):
        cell.text = ""
        cell.paragraphs[0].add_run(heading).bold = True
    for row in report.limited_rows():
        cells = table.add_row().cells
        for cell, value in zip(cells, row, strict=False):
            cell.text = as_text(value)
    if report.is_cut:
        document.add_paragraph(f"Showing the first {MAX_PAGE_ROWS} of {report.total_rows} rows. Use Excel for all.")

    footer = section.footer.paragraphs[0]
    footer.add_run(f"{report.footer_text}, page ").font.size = Pt(8)
    _add_field(footer, "PAGE")
    footer.add_run(" of ").font.size = Pt(8)
    _add_field(footer, "NUMPAGES")
    output = io.BytesIO()
    document.save(output)
    return output.getvalue()


# --- Responses -------------------------------------------------------------------------


def _file_response(content, content_type, report, extension):
    name = f"{slugify(report.title) or 'report'}_{timezone.localdate():%d-%m-%Y}.{extension}"
    response = HttpResponse(content, content_type=content_type)
    response["Content-Disposition"] = f'attachment; filename="{name}"'
    return response


def report_response(request, report, kind):
    """Excel or Word download, or the printable page. `kind` is "xlsx", "docx" or "print"."""
    logger.info("User %s made %s report %r (%s rows)", request.user.pk, kind, report.title, report.total_rows)
    if kind == "xlsx":
        return _file_response(to_excel(report), XLSX_TYPE, report, "xlsx")
    if kind == "docx":
        return _file_response(to_docx(report), DOCX_TYPE, report, "docx")
    if kind == "print":
        rows = [[as_text(value) for value in row] for row in report.limited_rows()]
        return render(request, "reports/print.html", {"report": report, "rows": rows})
    raise ValueError(f"Unknown report kind: {kind}")
