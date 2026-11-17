"""Private files: attach to any record, list, soft delete, and find a file for a checked download.

Every uploaded file lives in the private folder. Its URL (/files/private/...) goes through
PrivateFileView, which serves it only if the user may see the record that owns it.
"""
import logging
import os

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from core.access.services import can_change_files, can_remove_upload, can_see_record

from .models import FileAttachment

logger = logging.getLogger(__name__)

# Single file fields on records that are served through the checked view, e.g. Employee.profile_photo.
PROTECTED_FILE_FIELDS = []


def protect_file_field(model, field_name):
    """Call from an app's ready(). Example: protect_file_field(Employee, "profile_photo")."""
    if (model, field_name) not in PROTECTED_FILE_FIELDS:
        PROTECTED_FILE_FIELDS.append((model, field_name))


def attachments_for(record):
    """Files on this record that are not deleted, newest first."""
    return FileAttachment.objects.filter(
        content_type=ContentType.objects.get_for_model(record), object_id=record.pk, is_deleted=False
    ).select_related("uploaded_by")


def attach(record, uploaded_file, user):
    """Save an uploaded file on a record. Raises ValidationError with a user-facing message if refused."""
    if not can_see_record(user, record):
        logger.warning("User %s may not add files to %s #%s", user.pk, record._meta.label, record.pk)
        raise PermissionDenied("You cannot add files to this record.")
    if not can_change_files(user, record):
        logger.info("Refused upload to locked %s #%s", record._meta.label, record.pk)
        raise ValidationError(getattr(
            record, "files_locked_text",
            "This record is waiting for approval or already approved, so its files cannot change.",
        ))
    if uploaded_file is None:
        logger.info("Upload to %s #%s without a file", record._meta.label, record.pk)
        raise ValidationError("Choose a file first.")
    attachment = FileAttachment(
        record=record,
        file=uploaded_file,
        original_name=os.path.basename(uploaded_file.name)[:255],
        size=uploaded_file.size,
        uploaded_by=user,
    )
    attachment.full_clean()
    attachment.save()
    logger.info("User %s attached %r to %s #%s", user.pk, attachment.original_name, record._meta.label, record.pk)
    return attachment


def copy_attachment(attachment, record):
    """Give another record its own copy of a file. Example: a repeating rule's template copied to each new task.

    No user check: it is called by an app's own job after its rules are checked. Raises OSError if the
    file is missing on disk.
    """
    copy = FileAttachment(
        record=record, original_name=attachment.original_name, size=attachment.size, uploaded_by=attachment.uploaded_by
    )
    with attachment.file.open("rb"):
        copy.file.save(attachment.original_name, attachment.file, save=False)  # gets its own random stored name
    copy.save()
    return copy


def can_remove(attachment, user):
    return can_remove_upload(user, attachment.uploaded_by_id, attachment.record)


def remove(attachment, user):
    """Soft delete: hidden everywhere, kept on disk and in history."""
    if not can_remove(attachment, user):
        logger.warning("User %s may not delete attachment %s", user.pk, attachment.pk)
        raise PermissionDenied(
            "Only the person who uploaded this file, or an admin, can delete it, "
            "and not while the record waits for approval or once it is approved."
        )
    attachment.is_deleted = True
    attachment.deleted_by = user
    attachment.deleted_at = timezone.now()
    attachment.save()


def file_for_download(user, name):
    """(stored file, download name) if this user may download the stored file `name`, else None."""
    attachment = FileAttachment.objects.filter(file=name).first()
    if attachment is not None:
        if attachment.is_deleted or not can_see_record(user, attachment.record):
            return None
        return attachment.file, attachment.original_name
    for model, field_name in PROTECTED_FILE_FIELDS:
        record = model._default_manager.filter(**{field_name: name}).first()
        if record is not None:
            if not can_see_record(user, record):
                return None
            return getattr(record, field_name), os.path.basename(name)
    return None
