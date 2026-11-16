"""Record history (audit trail): who changed what, when, old value -> new value.

Changes are saved by django-simple-history. This module only turns them into readable lines,
leaving out fields the user may not see (e.g. bank details).
"""
from django.apps import apps
from simple_history.template_utils import HistoricalRecordContextHelper

from core.access.services import hidden_fields

ACTIONS = {"+": "Created", "~": "Changed", "-": "Deleted"}
NEVER_SHOWN = {"updated_at"}  # changes on every save, says nothing new


class ReadableValues(HistoricalRecordContextHelper):
    """Yes/No instead of True/False, a dash for empty values."""

    def prepare_delta_change_value(self, change, value):
        if value is None or value == "":
            return "—"
        if isinstance(value, bool):
            return "Yes" if value else "No"
        return super().prepare_delta_change_value(change, value)


def tracked_model(app_label, model_name):
    """The model if it keeps history, else None. Example: ("masters", "vendor") -> Vendor."""
    try:
        model = apps.get_model(app_label, model_name)
    except LookupError:
        return None
    return model if hasattr(model, "history") else None


def visible_changes(newer, older, user):
    """Field changes between two saved versions, without the fields hidden from this user.

    Example: [{"field": "Phone", "old": "98…", "new": "99…"}]
    """
    model = type(newer).instance_type
    excluded = NEVER_SHOWN | hidden_fields(model, user)
    delta = newer.diff_against(older, excluded_fields=excluded, foreign_keys_are_objs=True)
    return ReadableValues(model, newer).context_for_delta_changes(delta)


def record_history(record, user):
    """Every version of one record, newest first, as readable entries for the History page."""
    versions = list(record.history.select_related("history_user").order_by("-history_date", "-history_id"))
    entries = []
    for index, version in enumerate(versions):
        older = versions[index + 1] if index + 1 < len(versions) else None
        changes = visible_changes(version, older, user) if older is not None and version.history_type == "~" else []
        entries.append(
            {
                "when": version.history_date,
                "who": version.history_user or "System",
                "action": ACTIONS.get(version.history_type, "Changed"),
                "changes": changes,
            }
        )
    return entries
