from django.conf import settings
from django.urls import reverse
from django.utils.functional import SimpleLazyObject

from core.masters.services import own_photo_employee
from core.registry import apps_for_user


def environment(request):
    """`is_sandbox`: true on the test server, so every page can show the orange bar."""
    return {"is_sandbox": settings.IS_SANDBOX}


def app_menu(request):
    """`nav_apps`: the apps this user may open, for the sidebar. Worked out only if a page uses it."""
    return {"nav_apps": SimpleLazyObject(lambda: apps_for_user(request.user))}


def my_photo(request):
    """`my_photo_url`: link to the user's own photo for the top bar, or "" if none. Example: "/accounts/my-photo/?v=1731830000"."""

    def photo_url():
        employee = own_photo_employee(request.user)
        if employee is None:
            return ""
        return f"{reverse('accounts:my_photo')}?v={int(employee.updated_at.timestamp())}"

    return {"my_photo_url": SimpleLazyObject(photo_url)}
