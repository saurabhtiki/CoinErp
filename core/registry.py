"""App registry: each app tells the core its name, icon, link and (optional) dashboard widget.

An app registers itself once, in its AppConfig.ready(). Example:

    register(AppEntry(code="travel", name="Travel", icon="briefcase", url_name="travel:list"))

The sidebar and the home dashboard are built from this list, showing only the apps the
user may open (decided by the shared access layer, never here).
"""
import logging
from dataclasses import dataclass
from typing import Callable

from django.core.exceptions import ImproperlyConfigured
from django.urls import reverse

from core.access.services import apps_user_can_open

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AppEntry:
    code: str  # access-layer app code, the same text roles list in "allowed apps"
    name: str
    icon: str  # icon name from core/templatetags/icon_tags.py
    url_name: str  # where the sidebar link goes, e.g. "masters:list"
    url_args: tuple = ()
    description: str = ""  # shown as a tooltip and on the dashboard card
    order: int = 100  # smaller comes first in the sidebar
    widget_template: str = ""  # optional dashboard widget template
    widget_data: Callable | None = None  # function(user) -> dict for the widget template

    @property
    def url(self):
        return reverse(self.url_name, args=self.url_args)

    @property
    def section(self):
        """First part of the app's address, e.g. "/masters/". Pages under it light up the sidebar link."""
        return "/" + self.url.strip("/").split("/")[0] + "/"


_entries: dict[str, AppEntry] = {}


def register(entry):
    """Add an app. Registering the same code twice with different details is a mistake."""
    existing = _entries.get(entry.code)
    if existing is not None and existing != entry:
        raise ImproperlyConfigured(f"App code '{entry.code}' is already registered by another app.")
    _entries[entry.code] = entry


def all_apps():
    return sorted(_entries.values(), key=lambda entry: (entry.order, entry.name))


def apps_for_user(user):
    """Registered apps this user may open, in sidebar order."""
    entries = all_apps()
    allowed_codes = set(apps_user_can_open(user, [entry.code for entry in entries]))
    return [entry for entry in entries if entry.code in allowed_codes]


def dashboard_cards(user):
    """One card per app the user may open, with its widget data (or an error note)."""
    cards = []
    for entry in apps_for_user(user):
        card = {"app": entry, "data": None, "error": ""}
        if entry.widget_template and entry.widget_data:
            try:
                card["data"] = entry.widget_data(user)
            except Exception:  # one broken widget must not break the whole dashboard
                logger.exception("Dashboard widget for app '%s' failed", entry.code)
                card["error"] = "This summary could not be loaded. Please try again later."
        cards.append(card)
    return cards
