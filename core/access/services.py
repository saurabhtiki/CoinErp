"""The access rules, in one place.

Users get roles per company. Example: Ravi is "Tasks manager" in Acme and "Tasks clerk"
(own records only) in Globex.
1. Superuser sees everything.
2. Everyone else sees only companies where they have a role.
3. In each company, rows of an app are visible only if a role there opens that app.
   If every such role says "own records only", only rows they created are visible
   (Ravi: all Acme tasks, only his own Globex tasks).
4. A user may open an app if any of their company roles lists it.
"""
from django.apps import apps
from django.conf import settings
from django.db.models import Q


def _is_usable(user):
    return user is not None and user.is_authenticated and user.is_active


ROLE_LINKS_CACHE = "_access_role_links"


def _role_links(user):
    """(company id, allowed apps, own records only, needs 2FA) for each of the user's company roles.

    Read once per request: the result is kept on the user object (request.user is new each request),
    so the 2FA check, the sidebar and the access checks share one query.
    """
    links = getattr(user, ROLE_LINKS_CACHE, None)
    if links is None:
        links = list(
            user.company_roles.values_list(
                "company_id", "role__allowed_apps", "role__own_records_only", "role__requires_2fa"
            )
        )
        setattr(user, ROLE_LINKS_CACHE, links)
    return links


def allowed_companies(user):
    """Companies the user may see or pick in a form."""
    Company = apps.get_model("masters", "Company")
    if not _is_usable(user):
        return Company.objects.none()
    if user.is_superuser:
        return Company.objects.all()
    return Company.objects.filter(user_roles__user=user).distinct()


def companies_for_app(user, app_code):
    """Companies where one of the user's roles opens this app. Use for "which company?" choices.

    Example: Ravi has Masters in Acme and only Travel in Globex -> for "masters" only Acme.
    """
    Company = apps.get_model("masters", "Company")
    if not _is_usable(user):
        return Company.objects.none()
    if user.is_superuser:
        return Company.objects.all()
    all_rows, own_rows = app_access_by_company(user, app_code)
    return Company.objects.filter(pk__in=all_rows | own_rows)


def allowed_users(user):
    """Users the user may pick in a form: people with a role in at least one of their companies."""
    User = apps.get_model(settings.AUTH_USER_MODEL)
    if not _is_usable(user):
        return User.objects.none()
    if user.is_superuser:
        return User.objects.all()
    return User.objects.filter(company_roles__company__in=allowed_companies(user)).distinct()


def user_can_open_app(user, app_code):
    """True if one of the user's company roles lists this app (or the user is a superuser)."""
    return app_code in apps_user_can_open(user, [app_code])


def apps_user_can_open(user, app_codes):
    """The app codes (from app_codes) the user may open. One query, for building menus."""
    if not _is_usable(user):
        return []
    if user.is_superuser:
        return list(app_codes)
    granted = {code for _, codes, _, _ in _role_links(user) for code in (codes or [])}
    return [code for code in app_codes if code in granted]


def app_access_by_company(user, app_code):
    """Two sets of company ids for one app: where the user sees all rows, and where only own rows."""
    own_only_flags = {}
    for company_id, app_codes, own_only, _ in _role_links(user):
        if app_code in (app_codes or []):
            own_only_flags.setdefault(company_id, []).append(own_only)
    all_rows = {company_id for company_id, flags in own_only_flags.items() if not all(flags)}
    own_rows = set(own_only_flags) - all_rows
    return all_rows, own_rows


def visible_rows(queryset, user):
    """Filter any BaseModel queryset down to the rows this user may see."""
    if not _is_usable(user):
        return queryset.none()
    if user.is_superuser:
        return queryset
    all_rows, own_rows = app_access_by_company(user, queryset.model.access_app_code())
    return queryset.filter(Q(company_id__in=all_rows) | Q(company_id__in=own_rows, created_by=user))


def roles_require_2fa(user):
    """Superusers always need 2FA; others only if one of their roles says so."""
    if not _is_usable(user):
        return False
    return user.is_superuser or any(needs_2fa for *_, needs_2fa in _role_links(user))


def can_use_admin(user):
    """The admin site is for active staff only, never for external users (even if 'staff' is ticked)."""
    return _is_usable(user) and user.is_staff and not user.is_external


def can_change_company(user):
    """Company details (PAN, GSTN, CIN) are legal data: only the group admin (superuser) changes them."""
    return _is_usable(user) and user.is_superuser


def can_view_bank_details(user):
    """Vendor/customer bank fields are shown only with the "view bank details" permission."""
    return _is_usable(user) and user.has_perm("masters.view_bank_details")


def visible_records(model, user):
    """All rows of a model this user may see, for pages like History. Unknown kinds of model: none.

    Example: visible_records(Vendor, ravi) -> Ravi's Acme vendors only.
    """
    Company = apps.get_model("masters", "Company")
    if model is Company:
        return companies_for_app(user, "masters")
    rows = model._default_manager.all()
    if hasattr(rows, "for_user"):  # every BaseModel
        return rows.for_user(user)
    return rows.none()


def hidden_fields(model, user):
    """Fields this user may not see on screens, exports or history. Example: bank details."""
    if can_view_bank_details(user):
        return set()
    return set(getattr(model, "BANK_FIELDS", ()))


def can_see_record(user, record):
    """True if this user may see this one record (any kind with a rule in visible_records)."""
    return record is not None and visible_records(type(record), user).filter(pk=record.pk).exists()


def can_remove_upload(user, uploaded_by_id, record):
    """Files are removed by whoever uploaded them, or by staff, and only on records the user can see."""
    return can_see_record(user, record) and (uploaded_by_id == user.pk or can_use_admin(user))
