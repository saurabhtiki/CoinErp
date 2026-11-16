from django.utils.functional import SimpleLazyObject

from core.registry import apps_for_user


def app_menu(request):
    """`nav_apps`: the apps this user may open, for the sidebar. Worked out only if a page uses it."""
    return {"nav_apps": SimpleLazyObject(lambda: apps_for_user(request.user))}
