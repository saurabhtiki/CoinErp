"""Approval engine. Any record of any app can go through it. Example:

    request = submit(expense, ravi)            # Draft -> Waiting for approval (step 1: Manager)
    approve(request, asha, "OK")               # -> step 2: Finance
    approve(request, finance_head, "Paid")     # -> Approved

Rules (agreed in docs/plan.md):
- Steps run in order; any one approver of a step is enough.
- Nobody approves their own record: the submitter is left out; a step where they are the only approver is skipped.
- A step with nobody to approve stops the submit with a clear message.
- A step with a minimum amount is used only for amounts above it.
- A submitted record keeps the steps it started with, even if the flow changes later.
- Returned: back to the submitter to change and submit again (starts at step 1). Rejected: final.
- Withdraw: by the submitter, until someone has approved a step.
- While waiting or approved, the record cannot be changed.
"""
import logging

from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from core.access.services import can_act_on_approval, can_see_record
from core.notifications.services import notify

from .models import ApprovalAction, ApprovalFlow, ApprovalRequest, ApprovalStep

logger = logging.getLogger(__name__)
Status = ApprovalRequest.Status
Kind = ApprovalAction.Kind
ApproverType = ApprovalStep.ApproverType
LOCKED_STATUSES = (Status.SUBMITTED, Status.APPROVED)
MY_APPROVALS_LINK = "/approvals/"


# --- Reading --------------------------------------------------------------------------


def requests_for(record):
    """All submissions of a record, newest first."""
    return ApprovalRequest.objects.filter(
        content_type=ContentType.objects.get_for_model(record), object_id=record.pk
    )


def latest_request(record):
    return requests_for(record).first() if record.pk else None


def status_of(record):
    """"draft" if never submitted (or withdrawn), else the latest status. Example: "submitted"."""
    latest = latest_request(record)
    if latest is None or latest.status == Status.WITHDRAWN:
        return "draft"
    return latest.status


def is_locked(record):
    """True while waiting for approval or once approved: the record may not be changed."""
    latest = latest_request(record)
    return latest is not None and latest.status in LOCKED_STATUSES


def ensure_editable(record):
    if is_locked(record):
        logger.info("Blocked change to locked %s #%s", record._meta.label, record.pk)
        raise ValidationError("This record is waiting for approval or already approved, so it cannot be changed.")


def waiting_for(user):
    """Requests where this user is one of the current approvers. For "My approvals"."""
    return (
        ApprovalRequest.objects.filter(status=Status.SUBMITTED, current_approvers=user)
        .select_related("submitted_by", "company", "content_type")
        .prefetch_related("actions__user")
    )


def can_withdraw(request, user):
    return (
        request.status == Status.SUBMITTED
        and request.submitted_by_id == user.pk
        and not request.actions.filter(kind=Kind.APPROVE).exists()
    )


# --- Working out the steps -----------------------------------------------------------


def _amount_of(record):
    field = getattr(record, "approval_amount_field", None)
    return getattr(record, field) if field else None


def _step_applies(step, amount):
    """Steps with a minimum amount apply only above it. No amount on the record: the step applies."""
    return step.min_amount is None or amount is None or amount > step.min_amount


def _manager_user_id(submitter, company):
    Employee = apps.get_model("masters", "Employee")
    employee = Employee.objects.filter(company=company, user=submitter).select_related("reports_to").first()
    manager = employee.reports_to if employee else None
    return manager.user_id if manager else None


def _approver_ids(step_copy, company_id):
    """Active users who may approve one copied step right now."""
    User = apps.get_model("accounts", "User")
    kind = step_copy["approver_type"]
    if kind == ApproverType.ROLE:
        users = User.objects.filter(
            company_roles__company_id=company_id, company_roles__role_id=step_copy["role_id"]
        )
    else:
        users = User.objects.filter(pk=step_copy["user_id"])
    return set(users.filter(is_active=True).values_list("pk", flat=True))


def _copy_steps(flow, submitter, amount):
    """The flow's steps for this submission, each with who approves. Raises if a step has nobody."""
    copies = []
    for step in flow.steps.select_related("approver_role").order_by("order"):
        if not _step_applies(step, amount):
            continue
        copy = {"name": step.name, "approver_type": step.approver_type, "role_id": step.approver_role_id}
        copy["user_id"] = (
            _manager_user_id(submitter, flow.company) if step.approver_type == ApproverType.MANAGER
            else step.approver_user_id
        )
        if not _approver_ids(copy, flow.company_id):
            logger.warning("No approver for step %r in flow %s", step.name, flow.pk)
            raise ValidationError(f"No approver for step '{step.name}' in {flow.company}. Ask your admin.")
        copies.append(copy)
    if not copies:
        raise ValidationError(f"The approval flow for {flow.company} has no steps. Ask your admin.")
    if all(_approver_ids(copy, flow.company_id) == {submitter.pk} for copy in copies):
        raise ValidationError("You are the only approver in this flow, and nobody approves their own record. "
                              "Ask your admin to add another approver.")
    return copies


def _start_step(request, index):
    """Move to step `index`, skipping steps where the submitter is the only approver. Past the end: approved."""
    while index < len(request.steps):
        approvers = _approver_ids(request.steps[index], request.company_id)
        others = approvers - {request.submitted_by_id}
        if others or not approvers:
            if not approvers:
                logger.error("Approval %s step %r has nobody to approve it now", request.pk, request.steps[index]["name"])
            request.current_step = index
            request.save(update_fields=["current_step"])
            request.current_approvers.set(others)
            return
        index += 1
    request.status = Status.APPROVED
    request.finished_at = timezone.now()
    request.save(update_fields=["status", "finished_at"])
    request.current_approvers.clear()


def _tell_approvers(request):
    for approver in request.current_approvers.all():
        notify(approver, f"Approval needed: {request.record}",
               f"{request.submitted_by} asks for your approval (step: {request.step_name}).", link=MY_APPROVALS_LINK)


def _tell_submitter(request, title, remarks=""):
    message = f"Remarks: {remarks}" if remarks else ""
    notify(request.submitted_by, f"{title}: {request.record}", message, link=MY_APPROVALS_LINK)


# --- Actions --------------------------------------------------------------------------


def submit(record, user, remarks=""):
    """Send a record for approval. Raises ValidationError with a user-facing message if it cannot."""
    if not can_see_record(user, record):
        raise PermissionDenied("You cannot submit this record.")
    if status_of(record) in (*LOCKED_STATUSES, Status.REJECTED):
        raise ValidationError("This record was already submitted. It cannot be submitted again.")
    app_code = record._meta.app_label
    flow = ApprovalFlow.objects.filter(app_code=app_code, company_id=record.company_id, is_active=True).first()
    if flow is None:
        logger.warning("No approval flow for %s in company %s", app_code, record.company_id)
        raise ValidationError(f"No approval flow is set up for this app in {record.company}. Ask your admin.")
    amount = _amount_of(record)
    with transaction.atomic():
        request = ApprovalRequest.objects.create(
            record=record, company_id=record.company_id, app_code=app_code, flow=flow,
            steps=_copy_steps(flow, user, amount), amount=amount, submitted_by=user,
        )
        ApprovalAction.objects.create(request=request, kind=Kind.SUBMIT, user=user, remarks=remarks)
        _start_step(request, 0)
    _tell_approvers(request)
    return request


def _lock_for_action(request, user):
    """Fresh copy of the request, locked against a second approver acting at the same moment."""
    request = ApprovalRequest.objects.select_for_update().get(pk=request.pk)
    if not can_act_on_approval(user, request):
        logger.warning("User %s may not act on approval %s", user.pk, request.pk)
        raise PermissionDenied("This is not waiting for your approval.")
    return request


def approve(request, user, remarks=""):
    with transaction.atomic():
        request = _lock_for_action(request, user)
        ApprovalAction.objects.create(request=request, kind=Kind.APPROVE, step_name=request.step_name,
                                      user=user, remarks=remarks)
        _start_step(request, request.current_step + 1)
    if request.status == Status.APPROVED:
        _tell_submitter(request, "Approved", remarks)
    else:
        _tell_approvers(request)
    return request


def _finish(request, user, remarks, kind, status, title):
    if not remarks.strip():
        raise ValidationError("Please write remarks, so the submitter knows why.")
    with transaction.atomic():
        request = _lock_for_action(request, user)
        ApprovalAction.objects.create(request=request, kind=kind, step_name=request.step_name,
                                      user=user, remarks=remarks)
        request.status = status
        request.finished_at = timezone.now()
        request.save(update_fields=["status", "finished_at"])
        request.current_approvers.clear()
    _tell_submitter(request, title, remarks)
    return request


def send_back(request, user, remarks):
    """"Return": the submitter can change the record and submit it again."""
    return _finish(request, user, remarks, Kind.RETURN, Status.RETURNED, "Returned for changes")


def reject(request, user, remarks):
    """Final no."""
    return _finish(request, user, remarks, Kind.REJECT, Status.REJECTED, "Rejected")


def withdraw(request, user):
    if not can_withdraw(request, user):
        raise ValidationError("Only the submitter can withdraw, and only before anyone has approved it.")
    with transaction.atomic():
        ApprovalAction.objects.create(request=request, kind=Kind.WITHDRAW, user=user)
        request.status = Status.WITHDRAWN
        request.finished_at = timezone.now()
        request.save(update_fields=["status", "finished_at"])
        request.current_approvers.clear()
    return request
