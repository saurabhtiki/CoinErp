import logging

from django.apps import apps
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View

from core.access.services import visible_records

from . import services
from .models import ApprovalAction

logger = logging.getLogger(__name__)

ACTIONS = {
    "approve": (services.approve, "Approved"),
    "return": (services.send_back, "Returned for changes"),
    "reject": (services.reject, "Rejected"),
}


class MyApprovalsView(LoginRequiredMixin, View):
    """Records waiting for your approval, each with Approve / Return / Reject."""

    def get(self, request):
        return render(request, "approvals/my_approvals.html", {"items": services.waiting_for(request.user)})


class ActView(LoginRequiredMixin, View):
    """Approve, return or reject one request. Only its current approvers get past the lookup (404 for others)."""

    def post(self, request, pk):
        approval = get_object_or_404(services.waiting_for(request.user), pk=pk)
        action = request.POST.get("action")
        if action not in ACTIONS:
            raise Http404("Unknown action.")
        do_action, done_text = ACTIONS[action]
        remarks = request.POST.get("remarks", "")
        try:
            approval = do_action(approval, request.user, remarks)
        except ValidationError as refused:
            logger.info("Approval action %s refused for user %s: %s", action, request.user.pk, refused.messages)
            context = {"item": approval, "error": " ".join(refused.messages), "remarks": remarks}
            return render(request, "approvals/partials/card.html", context)
        if not request.htmx:
            return redirect("approvals:mine")
        return render(request, "approvals/partials/done.html", {"item": approval, "done_text": done_text})


def _visible_record(user, app_label, model_name, pk):
    try:
        model = apps.get_model(app_label, model_name)
    except LookupError:
        raise Http404("No such kind of record.") from None
    if not getattr(model, "uses_approvals", False):
        raise Http404("This kind of record has no approvals.")
    return get_object_or_404(visible_records(model, user), pk=pk)


class RecordApprovalView(LoginRequiredMixin, View):
    """Approval box for one record: status, trail, Submit / Withdraw. Apps include it on their record page:

        <div hx-get="{% url 'approvals:record' 'tasks' 'task' task.pk %}" hx-trigger="load"></div>
    """

    def get(self, request, app_label, model_name, pk):
        return self.render(request, _visible_record(request.user, app_label, model_name, pk))

    def post(self, request, app_label, model_name, pk):
        record = _visible_record(request.user, app_label, model_name, pk)
        error = None
        try:
            if request.POST.get("action") == "withdraw":
                latest = services.latest_request(record)
                if latest is None:
                    logger.info("Nothing to withdraw on %s #%s", record._meta.label, record.pk)
                    raise ValidationError("There is nothing to withdraw.")
                services.withdraw(latest, request.user)
            else:
                services.submit(record, request.user, request.POST.get("remarks", ""))
        except ValidationError as refused:
            error = " ".join(refused.messages)
        return self.render(request, record, error)

    @staticmethod
    def render(request, record, error=None):
        meta = record._meta
        latest = services.latest_request(record)
        status = services.status_of(record)
        context = {
            "record": record,
            "status": status,
            "latest": latest,
            "trail": ApprovalAction.objects.filter(request__in=services.requests_for(record)).select_related("user"),
            "can_submit": status in ("draft", "returned"),
            "can_withdraw": latest is not None and services.can_withdraw(latest, request.user),
            "panel_url": reverse("approvals:record", args=[meta.app_label, meta.model_name, record.pk]),
            "error": error,
        }
        return render(request, "approvals/partials/record_panel.html", context)
