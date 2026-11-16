"""The access rules, in one place.

Rules (example: Ravi works for ACME, role "Tasks clerk" = app "tasks", own records only):
1. Superuser sees everything.
2. Everyone else sees only rows of their companies (Ravi: ACME rows only).
3. If every role that opens an app says "own records only", the user sees only rows they
   created in that app (Ravi: only his own tasks).
4. A user may open an app only if one of their roles lists it.
"""
from django.apps import apps
from django.conf import settings


def _is_usable(user):
    return user is not None and user.is_authenticated and user.is_active


def allowed_companies(user):
    """Companies the user may see or pick in a form."""
    Company = apps.get_model("masters", "Company")
    if not _is_usable(user):
        return Company.objects.none()
    if user.is_superuser:
        return Company.objects.all()
    return user.companies.all()


def allowed_users(user):
    """Users the user may pick in a form: people who share at least one of their companies."""
    User = apps.get_model(settings.AUTH_USER_MODEL)
    if not _is_usable(user):
        return User.objects.none()
    if user.is_superuser:
        return User.objects.all()
    return User.objects.filter(companies__in=user.companies.all()).distinct()


def user_can_open_app(user, app_code):
    """True if one of the user's roles lists this app (or the user is a superuser)."""
    if not _is_usable(user):
        return False
    if user.is_superuser:
        return True
    return any(app_code in (apps or []) for apps in user.roles.values_list("allowed_apps", flat=True))


def user_sees_own_records_only(user, app_code):
    """True if every role that opens this app limits the user to their own records."""
    if not _is_usable(user) or user.is_superuser:
        return False
    granting_roles = [
        own_only
        for apps, own_only in user.roles.values_list("allowed_apps", "own_records_only")
        if app_code in (apps or [])
    ]
    return bool(granting_roles) and all(granting_roles)


def visible_rows(queryset, user):
    """Filter any BaseModel queryset down to the rows this user may see."""
    if not _is_usable(user):
        return queryset.none()
    if user.is_superuser:
        return queryset
    queryset = queryset.filter(company__in=user.companies.all())
    if user_sees_own_records_only(user, queryset.model.access_app_code()):
        queryset = queryset.filter(created_by=user)
    return queryset


def can_view_bank_details(user):
    """Vendor/customer bank fields are shown only with the "view bank details" permission."""
    return _is_usable(user) and user.has_perm("masters.view_bank_details")
