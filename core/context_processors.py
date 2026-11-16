from django.conf import settings
from django.utils.functional import SimpleLazyObject

from core.registry import apps_for_user


def environment(request):
    """`is_sandbox`: true on the test server, so every page can show the orange bar."""
    return {"is_sandbox": settings.IS_SANDBOX}


def app_menu(request):
    """`nav_apps`: the apps this user may open, for the sidebar. Worked out only if a page uses it."""
    return {"nav_apps": SimpleLazyObject(lambda: apps_for_user(request.user))}
