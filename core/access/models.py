from django.conf import settings
from django.db import models
from simple_history.models import HistoricalRecords

from . import services


class AccessQuerySet(models.QuerySet):
    def for_user(self, user):
        """Only the rows this user may see. Example: Note.objects.for_user(request.user)."""
        return services.visible_rows(self, user)


class BaseModel(models.Model):
    """Base for every business record: which company it belongs to and who made it.

    The app code used for access rules is the Django app label (e.g. "tasks").
    """

    company = models.ForeignKey("masters.Company", on_delete=models.PROTECT, related_name="+")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+", editable=False,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)

    objects = AccessQuerySet.as_manager()
    history = HistoricalRecords(inherit=True)  # every change: who, when, old -> new (core/audit)

    class Meta:
        abstract = True

    @classmethod
    def access_app_code(cls):
        return cls._meta.app_label
