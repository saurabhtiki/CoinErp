"""Record history (audit trail): who changed what, when, old value -> new value.

Changes are saved by django-simple-history. This module only turns them into readable lines,
leaving out fields the user may not see (e.g. bank details).
"""
import dataclasses

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


def changes_between(version_pairs, user):
    """Readable field changes for many (newer, older) version pairs of one model, in one go.

    Fields hidden from this user are left out. Linked records (e.g. Branch) are looked up once per
    field for all versions, not once per version. Example result for one pair:
    [{"field": "Phone", "old": "98…", "new": "99…"}]
    """
    if not version_pairs:
        return []
    model = type(version_pairs[0][0]).instance_type
    excluded = NEVER_SHOWN | hidden_fields(model, user)
    deltas = [newer.diff_against(older, excluded_fields=excluded) for newer, older in version_pairs]
    links = {f.name: f for f in model._meta.fields if f.many_to_one}
    wanted = {}
    for delta in deltas:
        for change in delta.changes:
            if change.field in links:
                wanted.setdefault(change.field, set()).update({change.old, change.new} - {None})
    names = {
        name: {pk: str(obj) for pk, obj in links[name].related_model._base_manager.in_bulk(ids).items()}
        for name, ids in wanted.items()
    }

    def readable(change):
        if change.field not in names:
            return change
        lookup = names[change.field]
        return dataclasses.replace(
            change,
            old=lookup.get(change.old, f"#{change.old} (deleted)") if change.old is not None else None,
            new=lookup.get(change.new, f"#{change.new} (deleted)") if change.new is not None else None,
        )

    results = []
    for (newer, _), delta in zip(version_pairs, deltas, strict=True):
        helper = ReadableValues(model, newer)
        results.append([
            {"field": formatted.field, "old": formatted.old, "new": formatted.new}
            for formatted in (helper.format_delta_change(readable(change)) for change in delta.changes)
        ])
    return results


def record_history(record, user):
    """Every version of one record, newest first, as readable entries for the History page."""
    versions = list(record.history.select_related("history_user").order_by("-history_date", "-history_id"))
    pairs = [(version, older) for version, older in zip(versions, versions[1:]) if version.history_type == "~"]
    changes_by_version = dict(zip((newer.pk for newer, _ in pairs), changes_between(pairs, user), strict=True))
    entries = []
    for version in versions:
        changes = changes_by_version.get(version.pk, [])
        entries.append(
            {
                "when": version.history_date,
                "who": version.history_user or "System",
                "action": ACTIONS.get(version.history_type, "Changed"),
                "changes": changes,
            }
        )
    return entries
