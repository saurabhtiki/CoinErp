from django.contrib import admin

from core.access import services
from core.access.admin import AccessModelAdmin, AppAccessAdminMixin

from .models import Branch, Company, CostCentre, Customer, Department, Employee, Vendor


@admin.register(Company)
class CompanyAdmin(AppAccessAdminMixin, admin.ModelAdmin):
    list_display = ("name", "code", "pan", "gstn", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "code", "pan", "gstn")

    def get_queryset(self, request):
        return services.allowed_companies(request.user)

    def has_add_permission(self, request):
        return request.user.is_superuser  # new companies are set up by the group admin only

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


@admin.register(Branch, Department, CostCentre)
class CompanyCodedAdmin(AccessModelAdmin):
    list_display = ("name", "code", "company", "is_active")
    list_filter = (("company", admin.RelatedOnlyFieldListFilter), "is_active")
    search_fields = ("name", "code")


@admin.register(Employee)
class EmployeeAdmin(AccessModelAdmin):
    list_display = ("employee_code", "first_name", "last_name", "company", "branch", "department", "designation")
    list_filter = (
        ("company", admin.RelatedOnlyFieldListFilter),
        ("branch", admin.RelatedOnlyFieldListFilter),
        ("department", admin.RelatedOnlyFieldListFilter),
        "is_active",
    )
    search_fields = ("employee_code", "first_name", "last_name", "email", "mobile")

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "user":
            kwargs["queryset"] = services.allowed_users(request.user)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(Vendor, Customer)
class PartyAdmin(AccessModelAdmin):
    list_display = ("name", "company", "pan", "gstn", "contact_person", "phone", "is_active")
    list_filter = (("company", admin.RelatedOnlyFieldListFilter), "is_active")
    search_fields = ("name", "pan", "gstn", "contact_person", "email")

    def get_exclude(self, request, obj=None):
        """Hide bank fields from users without the "view bank details" permission."""
        excluded = list(super().get_exclude(request, obj) or [])
        if not services.can_view_bank_details(request.user):
            excluded += self.model.BANK_FIELDS
        return excluded
