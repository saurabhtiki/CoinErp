from django.conf import settings
from django.db import models
from simple_history.models import HistoricalRecords


class BackupRecord(models.Model):
    """One backup file: the database plus the uploaded files, in one zip. System-wide, not per company.

    Every download changes `last_downloaded_*`, and the history keeps each change (who, when).
    """

    class Status(models.TextChoices):
        RUNNING = "running", "Running"
        OK = "ok", "Done"
        FAILED = "failed", "Failed"
        REMOVED = "removed", "Removed (old)"

    class Kind(models.TextChoices):
        AUTO = "auto", "Daily"
        MANUAL = "manual", "Backup now"

    file_name = models.CharField(max_length=200, blank=True)
    size_bytes = models.PositiveBigIntegerField(default=0)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.RUNNING)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.AUTO)
    error = models.TextField(blank=True)
    started_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    last_downloaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    last_downloaded_at = models.DateTimeField(null=True, blank=True)

    history = HistoricalRecords()

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.file_name or 'backup'} ({self.get_status_display()})"
