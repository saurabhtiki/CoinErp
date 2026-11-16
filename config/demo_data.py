"""Fake data for the sandbox: two companies, people with roles, tasks, a repeating task, holidays.

Nothing here is copied from real data. Every email ends in @demo.test. Run it with:
    python manage.py load_demo_data
"""
import logging
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from apps.tasks import services as task_services
from apps.tasks.models import TaskCategory
from core.accounts.models import CompanyRole, Role
from core.masters.models import Company, Employee

logger = logging.getLogger(__name__)
User = get_user_model()

DEMO_EMAIL_DOMAIN = "demo.test"
DEMO_COMPANY_CODE = "DEMOA"
DEFAULT_DEMO_PASSWORD = "demo-password-123"  # fake accounts on a test server only


class DemoDataExists(Exception):
    """The demo data is already there. Use reset_sandbox to start again."""


def demo_password():
    return getattr(settings, "DEMO_PASSWORD", "") or DEFAULT_DEMO_PASSWORD


def _make_user(name, company_roles, *, is_staff=False, is_external=False):
    user = User.objects.create_user(
        email=f"{name.lower()}@{DEMO_EMAIL_DOMAIN}", password=demo_password(), first_name=name,
        is_staff=is_staff, is_external=is_external,
    )
    for company, role in company_roles:
        CompanyRole.objects.create(user=user, company=company, role=role)
    return user


def _make_employee(company, user, code, designation, reports_to=None):
    return Employee.objects.create(
        company=company, user=user, employee_code=code, first_name=user.first_name,
        designation=designation, reports_to=reports_to, email=user.email,
    )


@transaction.atomic
def load_demo_data(today=None):
    """Create the demo data. Refuses if it was loaded before. Returns the demo users by name."""
    if Company.objects.filter(code=DEMO_COMPANY_CODE).exists():
        raise DemoDataExists("Demo data is already loaded. Run reset_sandbox to wipe it and start again.")
    today = today or timezone.localdate()

    admin_role, _ = Role.objects.get_or_create(name="Demo admin", defaults={"allowed_apps": ["tasks"]})
    member_role, _ = Role.objects.get_or_create(
        name="Demo member", defaults={"allowed_apps": ["tasks"], "own_records_only": True}
    )
    traders = Company.objects.create(name="Demo Traders Pvt Ltd", code=DEMO_COMPANY_CODE, address="1 Test Road, Pune")
    services_llp = Company.objects.create(name="Demo Services LLP", code="DEMOB", address="2 Sample Lane, Mumbai")

    admin = _make_user("Admin", [(traders, admin_role), (services_llp, admin_role)], is_staff=True)
    manager = _make_user("Manager", [(traders, member_role)])
    asha = _make_user("Asha", [(traders, member_role), (services_llp, member_role)])
    ravi = _make_user("Ravi", [(traders, member_role)])
    vendor = _make_user("Consultant", [(traders, member_role)], is_external=True)

    boss = _make_employee(traders, manager, "E001", "Finance manager")
    _make_employee(traders, asha, "E002", "Accountant", reports_to=boss)
    _make_employee(traders, ravi, "E003", "Executive", reports_to=boss)
    _make_employee(traders, vendor, "E900", "External consultant")
    _make_employee(services_llp, asha, "S001", "Accountant")

    category = TaskCategory.objects.create(company=traders, name="Compliance", created_by=admin)
    sample_tasks = [
        ("Prepare bank reconciliation", asha, -3, "high"),  # overdue
        ("Send Q2 invoices to customers", ravi, 0, "medium"),  # due today
        ("Collect vendor KYC forms", ravi, 5, "medium"),
        ("Review fixed asset register", asha, 12, "low"),
    ]
    for title, owner, days_from_today, priority in sample_tasks:
        task_services.create_task(
            manager, traders, title=title, owner=owner, due_date=today + timedelta(days=days_from_today),
            category=category, priority=priority, reviewer=manager if owner == asha else None,
            description="Demo task. Safe to change or delete.",
        )
    task_services.create_task(
        manager, traders, title="Share audit queries with the consultant", owner=vendor,
        due_date=today + timedelta(days=7), collaborators=[asha],
    )

    task_services.save_rule(
        manager, traders, title="GSTR1", owner=asha, reviewer=manager, category=category,
        frequency="monthly", due_day=11, due_in_next_period=True,
    )
    task_services.add_holiday(admin, traders, today + timedelta(days=20), "Demo holiday")
    logger.info("Demo data loaded for %s and %s", traders, services_llp)
    return {"admin": admin, "manager": manager, "asha": asha, "ravi": ravi, "consultant": vendor}
