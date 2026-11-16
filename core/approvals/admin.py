"""Approval flows are set up here. Example: "Tasks in Acme": 1. Manager, 2. Finance (over 100000)."""
from django.contrib import admin

from core.access import services
from core.access.admin import HistoryAdmin

from .models import ApprovalAction, ApprovalFlow, ApprovalRequest, ApprovalStep


class ApprovalStepInline(admin.TabularInline):
    model = ApprovalStep
    extra = 1
    fields = ["order", "name", "approver_type", "approver_user", "approver_role", "min_amount"]

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "approver_user":
            kwargs["queryset"] = services.allowed_users(request.user)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(ApprovalFlow)
class ApprovalFlowAdmin(HistoryAdmin):
    """Flows of the admin's own companies only. Changing a flow does not affect records already submitted."""

    list_display = ["name", "app_code", "company", "is_active"]
    list_filter = ["is_active", "app_code", ("company", admin.RelatedOnlyFieldListFilter)]
    inlines = [ApprovalStepInline]

    def get_queryset(self, request):
        return super().get_queryset(request).filter(company__in=services.allowed_companies(request.user))

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "company":
            kwargs["queryset"] = services.allowed_companies(request.user)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


class ApprovalActionInline(admin.TabularInline):
    model = ApprovalAction
    extra = 0
    can_delete = False
    readonly_fields = ["created_at", "kind", "step_name", "user", "remarks"]
    fields = readonly_fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(ApprovalRequest)
class ApprovalRequestAdmin(admin.ModelAdmin):
    """Read-only: every submission and its trail."""

    list_display = ["__str__", "app_code", "company", "submitted_by", "status", "submitted_at"]
    list_filter = ["status", "app_code", ("company", admin.RelatedOnlyFieldListFilter)]
    readonly_fields = ["record_name", "company", "app_code", "steps", "current_step", "amount", "status",
                       "submitted_by", "submitted_at", "finished_at"]
    fields = readonly_fields
    inlines = [ApprovalActionInline]

    @admin.display(description="Record")
    def record_name(self, obj):
        return str(obj.record or "Deleted record")

    def get_queryset(self, request):
        return super().get_queryset(request).filter(company__in=services.allowed_companies(request.user))

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
