from dataclasses import dataclass, field

from django.db.models import F
from django.http import Http404
from django.views import View
from django_datatable import CHOICE, Column, DataTable, table_response

from core.access import services
from core.access.mixins import AppAccessRequiredMixin
from core.reports import services as reports

from .services import master_report

from .models import Branch, Company, CostCentre, Customer, Department, Employee, Vendor


@dataclass
class MasterList:
    """How one master's list screen looks. Rows always come through the access layer."""

    model: type
    title: str
    columns: list
    search_fields: tuple
    annotations: dict = field(default_factory=dict)

    def rows_for(self, user):
        if self.model is Company:
            rows = services.companies_for_app(user, "masters")
        else:
            rows = self.model.objects.for_user(user).annotate(company_code=F("company__code"))
        return rows.annotate(**self.annotations)


COMPANY_COLUMN = Column("company_code", "Company", type=CHOICE)
ACTIVE_COLUMN = Column("is_active", "Active", type=CHOICE, choices={True: "Yes", False: "No"})


def coded_list(model, title):
    return MasterList(
        model, title, [Column("name", "Name"), Column("code", "Code"), COMPANY_COLUMN, ACTIVE_COLUMN], ("name", "code")
    )


def party_list(model, title):
    columns = [
        Column("name", "Name"),
        COMPANY_COLUMN,
        Column("pan", "PAN"),
        Column("gstn", "GSTN"),
        Column("contact_person", "Contact"),
        Column("phone", "Phone"),
        ACTIVE_COLUMN,
    ]
    return MasterList(model, title, columns, ("name", "pan", "gstn", "contact_person"))


MASTER_LISTS = {
    "companies": MasterList(
        Company,
        "Companies",
        [Column("name", "Name"), Column("code", "Code"), Column("pan", "PAN"), Column("gstn", "GSTN"), ACTIVE_COLUMN],
        ("name", "code", "pan", "gstn"),
    ),
    "branches": coded_list(Branch, "Branches"),
    "departments": coded_list(Department, "Departments"),
    "cost-centres": coded_list(CostCentre, "Cost centres"),
    "employees": MasterList(
        Employee,
        "Employees",
        [
            Column("employee_code", "Code"),
            Column("first_name", "First name"),
            Column("last_name", "Last name"),
            COMPANY_COLUMN,
            Column("branch_name", "Branch", type=CHOICE),
            Column("department_name", "Department", type=CHOICE),
            Column("designation", "Designation", type=CHOICE),
            ACTIVE_COLUMN,
        ],
        ("employee_code", "first_name", "last_name", "email", "mobile"),
        annotations={"branch_name": F("branch__name"), "department_name": F("department__name")},
    ),
    "vendors": party_list(Vendor, "Vendors"),
    "customers": party_list(Customer, "Customers"),
}


class MasterListView(AppAccessRequiredMixin, View):
    """One list screen for every master. Example: /masters/branches/."""

    app_code = "masters"

    def get(self, request, master):
        config = MASTER_LISTS.get(master)
        if config is None:
            raise Http404("No such master list.")
        table = DataTable(
            request.GET,
            config.rows_for(request.user),
            config.columns,
            table_id=f"{master}-table",
            default_sort=(config.columns[0].name,),
            base_url=request.path,
            search_fields=config.search_fields,
            noun=config.title.lower(),
        )
        kind = request.GET.get("report")
        if kind in reports.KINDS:
            return reports.report_response(request, master_report(request.user, config, table.ordered), kind)
        context = {
            "table": table,
            "report_links": [
                (label, request.path + table.url(drop={"page"}, add=[("report", kind)]))
                for kind, label in reports.KINDS.items()
            ],
            "title": config.title,
            "master_lists": MASTER_LISTS,
            "change_url_name": f"admin:masters_{config.model._meta.model_name}_change",
            "add_url_name": f"admin:masters_{config.model._meta.model_name}_add",
            "model_name": config.model._meta.model_name,
            # Add/Edit open the admin screens, which only staff may use; others get a view-only list.
            "can_edit": services.can_use_admin(request.user),
        }
        return table_response(request, table, "masters/list.html", "masters/partials/table.html", context)
