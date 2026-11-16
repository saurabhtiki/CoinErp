"""Approval engine: Manager -> Finance (over 1,00,000) on the test-only Expense model.

People in Acme: Ravi (clerk, submits), Asha (Ravi's manager), Farah (finance). Gita works in Globex.
"""
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.exceptions import PermissionDenied, ValidationError

from core.accounts.models import CompanyRole, Role
from core.approvals import services
from core.approvals.models import ApprovalFlow, ApprovalStep
from core.masters.models import Company, Employee
from core.notifications.models import Notification
from tests.access_demo.models import Expense

User = get_user_model()
PASSWORD = "a-long-password-123"
APP = "access_demo"
pytestmark = pytest.mark.django_db


@pytest.fixture
def acme():
    return Company.objects.create(name="Acme", code="ACME")


@pytest.fixture
def clerk_role():
    return Role.objects.create(name="Clerk", allowed_apps=[APP], own_records_only=True)


@pytest.fixture
def finance_role():
    return Role.objects.create(name="Finance", allowed_apps=[APP], own_records_only=True)


def person(email, company, role, first_name):
    user = User.objects.create_user(email=email, password=PASSWORD, first_name=first_name)
    CompanyRole.objects.create(user=user, company=company, role=role)
    return user


@pytest.fixture
def ravi(acme, clerk_role):
    return person("ravi@example.com", acme, clerk_role, "Ravi")


@pytest.fixture
def asha(acme, clerk_role):
    return person("asha@example.com", acme, clerk_role, "Asha")


@pytest.fixture
def farah(acme, finance_role):
    return person("farah@example.com", acme, finance_role, "Farah")


@pytest.fixture
def gita(clerk_role):
    globex = Company.objects.create(name="Globex", code="GLOBEX")
    return person("gita@example.com", globex, clerk_role, "Gita")


@pytest.fixture
def ravi_reports_to_asha(acme, ravi, asha):
    boss = Employee.objects.create(company=acme, employee_code="E1", first_name="Asha", user=asha)
    Employee.objects.create(company=acme, employee_code="E2", first_name="Ravi", user=ravi, reports_to=boss)


@pytest.fixture
def flow(acme, finance_role, ravi_reports_to_asha, farah):
    flow = ApprovalFlow.objects.create(app_code=APP, company=acme, name="Expense approval")
    ApprovalStep.objects.create(flow=flow, order=1, name="Manager", approver_type="manager")
    ApprovalStep.objects.create(flow=flow, order=2, name="Finance", approver_type="role",
                                approver_role=finance_role, min_amount=Decimal("100000"))
    return flow


def expense(company, user, amount="200000"):
    return Expense.objects.create(company=company, created_by=user, title="Laptops", amount=Decimal(amount))


def approver_emails(request):
    return sorted(request.current_approvers.values_list("email", flat=True))


# --- The normal path -------------------------------------------------------------------


def test_big_amount_goes_manager_then_finance_then_approved(acme, ravi, asha, farah, flow):
    record = expense(acme, ravi)

    request = services.submit(record, ravi)
    assert (request.step_name, approver_emails(request)) == ("Manager", ["asha@example.com"])
    assert Notification.objects.filter(user=asha, title="Approval needed: Laptops").exists()

    request = services.approve(request, asha, "OK")
    assert (request.step_name, approver_emails(request)) == ("Finance", ["farah@example.com"])

    request = services.approve(request, farah)
    assert request.status == "approved" and request.finished_at
    assert services.status_of(record) == "approved"
    assert Notification.objects.filter(user=ravi, title="Approved: Laptops").exists()
    assert [action.kind for action in request.actions.all()] == ["submit", "approve", "approve"]


def test_small_amount_skips_the_finance_step(acme, ravi, asha, flow):
    request = services.submit(expense(acme, ravi, amount="5000"), ravi)

    request = services.approve(request, asha)

    assert request.status == "approved"
    assert [step["name"] for step in request.steps] == ["Manager"]


def test_approvers_get_an_email(acme, ravi, flow):
    services.submit(expense(acme, ravi), ravi)

    assert [message.to for message in mail.outbox] == [["asha@example.com"]]


# --- Return, reject, withdraw ----------------------------------------------------------


def test_returned_record_can_be_changed_and_starts_again_at_step_one(acme, ravi, asha, flow):
    record = expense(acme, ravi)
    request = services.submit(record, ravi)
    services.approve(request, asha)
    request.refresh_from_db()
    services.send_back(request, request.current_approvers.get(), "Add the quote")

    assert services.status_of(record) == "returned"
    record.title = "Laptops (with quote)"
    record.save()  # editable again

    second = services.submit(record, ravi)
    assert (second.current_step, second.step_name) == (0, "Manager")
    assert Notification.objects.filter(user=ravi, title__startswith="Returned for changes").exists()


def test_rejected_is_final(acme, ravi, asha, flow):
    record = expense(acme, ravi)
    services.reject(services.submit(record, ravi), asha, "Not in budget")

    with pytest.raises(ValidationError, match="cannot be submitted again"):
        services.submit(record, ravi)


@pytest.mark.parametrize("action", [services.reject, services.send_back])
def test_reject_and_return_need_remarks(acme, ravi, asha, flow, action):
    request = services.submit(expense(acme, ravi), ravi)

    with pytest.raises(ValidationError, match="write remarks"):
        action(request, asha, "  ")


def test_withdraw_until_someone_approves(acme, ravi, asha, flow):
    record = expense(acme, ravi)
    services.withdraw(services.submit(record, ravi), ravi)
    assert services.status_of(record) == "draft"
    record.save()  # editable again

    request = services.approve(services.submit(record, ravi), asha)
    with pytest.raises(ValidationError, match="before anyone has approved"):
        services.withdraw(request, ravi)


def test_only_the_submitter_can_withdraw(acme, ravi, asha, flow):
    request = services.submit(expense(acme, ravi), ravi)

    with pytest.raises(ValidationError):
        services.withdraw(request, asha)


# --- Who approves ----------------------------------------------------------------------


def test_nobody_approves_their_own_record(acme, ravi, asha, ravi_reports_to_asha):
    flow = ApprovalFlow.objects.create(app_code=APP, company=acme, name="Self check")
    ApprovalStep.objects.create(flow=flow, order=1, name="Ravi", approver_type="user", approver_user=ravi)
    ApprovalStep.objects.create(flow=flow, order=2, name="Manager", approver_type="manager")

    request = services.submit(expense(acme, ravi), ravi)

    assert (request.step_name, approver_emails(request)) == ("Manager", ["asha@example.com"])


def test_submitter_is_left_out_of_a_role_step(acme, ravi, farah, finance_role):
    CompanyRole.objects.create(user=ravi, company=acme, role=finance_role)
    flow = ApprovalFlow.objects.create(app_code=APP, company=acme, name="Finance only")
    ApprovalStep.objects.create(flow=flow, order=1, name="Finance", approver_type="role", approver_role=finance_role)

    request = services.submit(expense(acme, ravi), ravi)

    assert approver_emails(request) == ["farah@example.com"]


def test_submitter_as_the_only_approver_is_refused(acme, ravi):
    flow = ApprovalFlow.objects.create(app_code=APP, company=acme, name="Only Ravi")
    ApprovalStep.objects.create(flow=flow, order=1, name="Ravi", approver_type="user", approver_user=ravi)

    with pytest.raises(ValidationError, match="only approver"):
        services.submit(expense(acme, ravi), ravi)


def test_no_manager_stops_the_submit_with_a_clear_message(acme, ravi):
    flow = ApprovalFlow.objects.create(app_code=APP, company=acme, name="Manager only")
    ApprovalStep.objects.create(flow=flow, order=1, name="Manager", approver_type="manager")

    with pytest.raises(ValidationError, match="No approver for step 'Manager' in Acme. Ask your admin."):
        services.submit(expense(acme, ravi), ravi)


def test_no_flow_stops_the_submit(acme, ravi):
    with pytest.raises(ValidationError, match="No approval flow"):
        services.submit(expense(acme, ravi), ravi)


def test_flow_changes_do_not_affect_submitted_records(acme, ravi, asha, farah, flow):
    request = services.submit(expense(acme, ravi), ravi)
    flow.steps.filter(name="Finance").delete()
    ApprovalStep.objects.create(flow=flow, order=3, name="Director", approver_type="user", approver_user=asha)

    request = services.approve(request, asha)

    assert request.step_name == "Finance"
    assert services.approve(request, farah).status == "approved"


def test_only_current_approvers_can_act(acme, ravi, farah, gita, flow):
    request = services.submit(expense(acme, ravi), ravi)

    for outsider in (farah, gita, ravi):  # Finance is step 2; Gita is another company; Ravi submitted
        with pytest.raises(PermissionDenied):
            services.approve(request, outsider)


# --- Lock and visibility ---------------------------------------------------------------


def test_record_is_locked_while_waiting_and_once_approved(acme, ravi, asha, flow):
    record = expense(acme, ravi, amount="5000")
    services.submit(record, ravi)

    with pytest.raises(ValidationError, match="cannot be changed"):
        record.save()

    services.approve(services.latest_request(record), asha)
    with pytest.raises(ValidationError, match="cannot be changed"):
        record.save()


def test_approver_sees_the_record_only_while_it_waits_for_them(acme, ravi, asha, flow):
    record = expense(acme, ravi, amount="5000")  # Asha's role: own records only
    assert record not in Expense.objects.for_user(asha)

    services.submit(record, ravi)
    assert record in Expense.objects.for_user(asha)

    services.approve(services.latest_request(record), asha)
    assert record not in Expense.objects.for_user(asha)


# --- Screens ---------------------------------------------------------------------------


def test_my_approvals_lists_waiting_records_with_a_count(client, acme, ravi, asha, flow):
    services.submit(expense(acme, ravi), ravi)
    client.force_login(asha)

    content = client.get("/approvals/").content.decode()

    assert "Laptops" in content and "Approve" in content
    assert 'id="approvals-count"' in content


def test_approve_from_the_screen(client, acme, ravi, asha, flow):
    request = services.submit(expense(acme, ravi), ravi)
    client.force_login(asha)

    response = client.post(f"/approvals/{request.pk}/act/", {"action": "approve"}, HTTP_HX_REQUEST="true")

    assert b"Sent to the next step (Finance)" in response.content
    request.refresh_from_db()
    assert request.step_name == "Finance"


def test_reject_from_the_screen_without_remarks_shows_the_message(client, acme, ravi, asha, flow):
    request = services.submit(expense(acme, ravi), ravi)
    client.force_login(asha)

    response = client.post(f"/approvals/{request.pk}/act/", {"action": "reject"}, HTTP_HX_REQUEST="true")

    assert b"Please write remarks" in response.content
    request.refresh_from_db()
    assert request.status == "submitted"


def test_others_cannot_act_from_the_screen(client, acme, ravi, gita, flow):
    request = services.submit(expense(acme, ravi), ravi)
    client.force_login(gita)

    assert client.post(f"/approvals/{request.pk}/act/", {"action": "approve"}).status_code == 404


def test_record_panel_submit_and_status(client, acme, ravi, flow):
    record = expense(acme, ravi)
    url = f"/approvals/record/{APP}/expense/{record.pk}/"
    client.force_login(ravi)

    assert b"Submit for approval" in client.get(url).content
    response = client.post(url, {"action": "submit"}, HTTP_HX_REQUEST="true")

    assert b"Waiting: Manager" in response.content
    assert b"Withdraw" in response.content


def test_record_panel_shows_the_reason_when_submit_fails(client, acme, ravi):
    record = expense(acme, ravi)
    client.force_login(ravi)

    response = client.post(f"/approvals/record/{APP}/expense/{record.pk}/", {"action": "submit"})

    assert b"No approval flow" in response.content


def test_record_panel_of_another_company_is_not_found(client, acme, ravi, gita, flow):
    record = expense(acme, ravi)
    client.force_login(gita)

    assert client.get(f"/approvals/record/{APP}/expense/{record.pk}/").status_code == 404
