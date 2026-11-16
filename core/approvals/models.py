"""Approval engine data. Example flow: "Tasks in Acme: Manager -> Finance (over ₹1,00,000)".

- ApprovalFlow + ApprovalStep: set up by an admin, per app and company.
- ApprovalRequest: one submission of one record. It keeps a copy of the steps it started with.
- ApprovalAction: every submit / approve / return / reject / withdraw, with who, when and remarks.
"""
from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models
from simple_history.models import HistoricalRecords


class ApprovalFlow(models.Model):
    app_code = models.CharField(max_length=50, help_text='App this flow is for, e.g. "tasks".')
    company = models.ForeignKey("masters.Company", on_delete=models.PROTECT, related_name="+")
    name = models.CharField(max_length=100, help_text='e.g. "Expense approval".')
    is_active = models.BooleanField(default=True)

    history = HistoricalRecords()

    class Meta:
        ordering = ["company", "app_code"]
        constraints = [models.UniqueConstraint(fields=["app_code", "company"], name="one_flow_per_app_per_company")]

    def __str__(self):
        return f"{self.name} ({self.app_code}, {self.company})"


class ApprovalStep(models.Model):
    class ApproverType(models.TextChoices):
        USER = "user", "A named person"
        ROLE = "role", "Anyone with a role in the company"
        MANAGER = "manager", "The submitter's manager"

    flow = models.ForeignKey(ApprovalFlow, on_delete=models.CASCADE, related_name="steps")
    order = models.PositiveSmallIntegerField(help_text="Steps run from the lowest number up.")
    name = models.CharField(max_length=100, help_text='Shown to users, e.g. "Finance".')
    approver_type = models.CharField(max_length=10, choices=ApproverType.choices)
    approver_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+",
        help_text='Only for "A named person".',
    )
    approver_role = models.ForeignKey(
        "accounts.Role", null=True, blank=True, on_delete=models.PROTECT, related_name="+",
        help_text='Only for "Anyone with a role".',
    )
    min_amount = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True,
        help_text="Leave empty to always use this step. If set, the step is used only for amounts above it.",
    )

    history = HistoricalRecords()

    class Meta:
        ordering = ["flow", "order"]
        constraints = [models.UniqueConstraint(fields=["flow", "order"], name="unique_step_order_per_flow")]

    def __str__(self):
        return f"{self.order}. {self.name}"

    def clean(self):
        errors = {}
        if self.approver_type == self.ApproverType.USER and not self.approver_user_id:
            errors["approver_user"] = "Pick the person who approves this step."
        if self.approver_type == self.ApproverType.ROLE and not self.approver_role_id:
            errors["approver_role"] = "Pick the role that approves this step."
        if errors:
            raise ValidationError(errors)


class ApprovalRequest(models.Model):
    class Status(models.TextChoices):
        SUBMITTED = "submitted", "Waiting for approval"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        RETURNED = "returned", "Returned for changes"
        WITHDRAWN = "withdrawn", "Withdrawn"

    content_type = models.ForeignKey(ContentType, on_delete=models.PROTECT, related_name="+")
    object_id = models.PositiveBigIntegerField()
    record = GenericForeignKey("content_type", "object_id")
    company = models.ForeignKey("masters.Company", on_delete=models.PROTECT, related_name="+")
    app_code = models.CharField(max_length=50)
    flow = models.ForeignKey(ApprovalFlow, null=True, on_delete=models.SET_NULL, related_name="+")
    steps = models.JSONField(default=list, help_text="Copy of the steps at submit time.")
    current_step = models.PositiveSmallIntegerField(default=0)
    current_approvers = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="+")
    amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.SUBMITTED)
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    submitted_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-submitted_at", "-id"]
        indexes = [models.Index(fields=["content_type", "object_id"], name="approval_record_idx")]

    def __str__(self):
        return f"{self.record or 'Deleted record'}: {self.get_status_display()}"

    @property
    def step_name(self):
        if self.status == self.Status.SUBMITTED and self.current_step < len(self.steps):
            return self.steps[self.current_step]["name"]
        return ""


class ApprovalAction(models.Model):
    class Kind(models.TextChoices):
        SUBMIT = "submit", "Submitted"
        APPROVE = "approve", "Approved"
        RETURN = "return", "Returned for changes"
        REJECT = "reject", "Rejected"
        WITHDRAW = "withdraw", "Withdrawn"

    request = models.ForeignKey(ApprovalRequest, on_delete=models.CASCADE, related_name="actions")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    step_name = models.CharField(max_length=100, blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    remarks = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"{self.get_kind_display()} by {self.user}"
