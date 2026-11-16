"""Masters business logic."""
from core.access.services import companies_for_app
from core.reports import services as reports

from .models import Customer, Employee, Vendor


TEAM_CACHE = "_masters_team_by_company"


def team_user_ids_by_company(user):
    """Logins of everyone who reports to this user, at any level, per company.

    Example: Foram reports to Saurabh and Ghosh reports to Foram, both in Acme
    -> {acme.pk: {foram.pk, ghosh.pk}} for Saurabh. Read once per request (kept on the user object).
    """
    team = getattr(user, TEAM_CACHE, None)
    if team is not None:
        return team
    team = {}
    seen = set(Employee.objects.filter(user=user, is_active=True).values_list("pk", flat=True))
    level = set(seen)
    while level:
        reports = Employee.objects.filter(reports_to__in=level, is_active=True).exclude(pk__in=seen)
        level = set()
        for employee_id, company_id, user_id in reports.values_list("pk", "company_id", "user_id"):
            level.add(employee_id)
            if user_id:
                team.setdefault(company_id, set()).add(user_id)
        seen |= level
    setattr(user, TEAM_CACHE, team)
    return team


def dashboard_counts(user):
    """How many records of each main master the user can see. Example: Companies 2, Vendors 14."""
    counts = [
        ("companies", "Companies", companies_for_app(user, "masters")),
        ("employees", "Employees", Employee.objects.for_user(user)),
        ("vendors", "Vendors", Vendor.objects.for_user(user)),
        ("customers", "Customers", Customer.objects.for_user(user)),
    ]
    return {"counts": [{"slug": slug, "title": title, "count": rows.count()} for slug, title, rows in counts]}


def _column_getter(column):
    """Field name, or a function that turns a stored value into its label (e.g. True -> "Yes")."""
    if not column.choices:
        return column.name
    return lambda row: column.choices.get(getattr(row, column.name), getattr(row, column.name))


def master_report(user, config, rows):
    """A master list as a report, with the filters and sort the user picked.

    Header: the company, if the user works in just one; else "all your companies".
    """
    companies = companies_for_app(user, "masters")
    company = companies.first() if companies.count() == 1 else None
    columns = [(column.label, _column_getter(column)) for column in config.columns]
    return reports.make_report(user, config.title, columns, rows, company=company, model=config.model)
