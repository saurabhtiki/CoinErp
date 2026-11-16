from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from . import services
from .forms import UserInviteForm
from .models import CompanyRole, Role, User


def staff_only_has_permission(request):
    """External users never get the admin site, even if someone ticks 'staff'."""
    user = request.user
    return user.is_active and user.is_staff and not user.is_external


admin.site.has_permission = staff_only_has_permission
admin.site.site_header = "Group ERP admin"


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ["name", "allowed_apps", "own_records_only", "requires_2fa"]
    list_filter = ["own_records_only", "requires_2fa"]
    search_fields = ["name"]


class CompanyRoleInline(admin.TabularInline):
    """Which role the user has in which company. Example: Acme → Manager, Globex → Admin."""

    model = CompanyRole
    extra = 1
    verbose_name_plural = "Company roles (the user sees only these companies)"


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    add_form = UserInviteForm
    add_fieldsets = [(None, {"fields": ["email", "first_name", "last_name", "is_external"]})]
    fieldsets = [
        (None, {"fields": ["email", "password"]}),
        ("Person", {"fields": ["first_name", "last_name", "is_external"]}),
        ("Access", {"fields": ["is_active", "is_staff", "is_superuser"]}),
        ("Dates", {"fields": ["last_login", "date_joined"]}),
    ]
    readonly_fields = ["last_login", "date_joined"]
    inlines = [CompanyRoleInline]
    list_display = ["email", "first_name", "last_name", "is_external", "is_active", "last_login"]
    list_filter = ["is_external", "is_active", "is_staff", "company_roles__company", "company_roles__role"]
    search_fields = ["email", "first_name", "last_name"]
    ordering = ["email"]
    actions = ["resend_invite"]

    def get_inlines(self, request, obj):
        return self.inlines if obj else []  # add roles after the user is created

    def save_model(self, request, obj, form, change):
        if not change:
            obj.set_unusable_password()
        super().save_model(request, obj, form, change)
        if not change:
            self._invite(request, obj)

    @admin.action(description="Send invite email again")
    def resend_invite(self, request, queryset):
        for user in queryset:
            self._invite(request, user)

    def _invite(self, request, user):
        try:
            services.send_invite(user, request)
        except OSError:
            self.message_user(
                request,
                f"Could not send the invite email to {user.email}. Check email settings, then use "
                "'Send invite email again'.",
                messages.ERROR,
            )
        else:
            self.message_user(request, f"Invite email sent to {user.email}.", messages.SUCCESS)
