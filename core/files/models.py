import os
import uuid

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone
from simple_history.models import HistoricalRecords

from .validators import validate_attachment


def attachment_path(instance, filename):
    """Random stored name, so names never clash or leak. The real name is kept in original_name."""
    extension = os.path.splitext(filename)[1].lower()
    return f"attachments/{timezone.now():%Y/%m}/{uuid.uuid4().hex}{extension}"


class FileAttachment(models.Model):
    """A file linked to any record. Example: a GST certificate on Vendor "Steel Co".

    Who may see it follows the record: if you can see the vendor, you can download its files.
    Deleting only hides the file (is_deleted); it stays on disk and in history.
    """

    content_type = models.ForeignKey(ContentType, on_delete=models.PROTECT, related_name="+")
    object_id = models.PositiveBigIntegerField()
    record = GenericForeignKey("content_type", "object_id")
    file = models.FileField(upload_to=attachment_path, validators=[validate_attachment])
    original_name = models.CharField(max_length=255)
    size = models.PositiveBigIntegerField()
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)
    is_deleted = models.BooleanField(default=False)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    deleted_at = models.DateTimeField(null=True, blank=True)

    history = HistoricalRecords()

    class Meta:
        ordering = ["-uploaded_at", "-id"]
        indexes = [models.Index(fields=["content_type", "object_id"], name="attachment_record_idx")]

    def __str__(self):
        return self.original_name
