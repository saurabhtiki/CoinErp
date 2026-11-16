"""Backups: one zip with the database dump and the uploaded files.

    start_backup(user)      make the record and queue the job (the worker runs it)
    run_backup(record_id)   the job: dump, zip, keep the newest 14 + one per week for 8 weeks
    record_download(...)    note who downloaded a file

Restoring is done only on the server with docker/restore_backup.sh.
"""
import logging
import os
import sqlite3
import subprocess
import tempfile
import zipfile
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection
from django.utils import timezone
from django_q.tasks import async_task

from core.notifications.services import notify

from .models import BackupRecord

logger = logging.getLogger(__name__)
Status = BackupRecord.Status
STALE_AFTER = timedelta(hours=2)  # a backup "running" longer than this is counted as stuck
DUMP_TIMEOUT_SECONDS = 1800


class BackupError(Exception):
    """A backup step failed. The message is shown on the Backups page."""


def can_manage_backups(user):
    """Only active superusers see, make and download backups."""
    return bool(user.is_authenticated and user.is_active and user.is_superuser)


def backup_folder():
    folder = Path(settings.BACKUP_ROOT)
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def backup_path(record):
    return backup_folder() / record.file_name


def start_backup(user=None):
    """Make the record and queue the job. The daily job passes no user."""
    still_running = BackupRecord.objects.filter(status=Status.RUNNING, created_at__gte=timezone.now() - STALE_AFTER)
    if still_running.exists():
        raise ValidationError("A backup is already running. Wait until it is done.")
    kind = BackupRecord.Kind.MANUAL if user else BackupRecord.Kind.AUTO
    record = BackupRecord.objects.create(kind=kind, started_by=user)
    async_task("core.backups.services.run_backup", record.pk)
    return record


def scheduled_backup():
    """Called every day by the schedule (see setup_backup_jobs)."""
    try:
        start_backup()
    except ValidationError as error:
        logger.warning("Daily backup skipped: %s", error.message)


def run_backup(record_id):
    """The job: build the zip, then tidy old backups. Failures are logged, saved and emailed to the superusers."""
    record = BackupRecord.objects.get(pk=record_id)
    record.file_name = f"backup-{timezone.localtime(record.created_at):%Y%m%d-%H%M%S}-{record.pk}.zip"
    partial = backup_path(record).with_suffix(".partial")
    try:
        _build_zip(partial)
        partial.rename(backup_path(record))
    except (OSError, sqlite3.Error, subprocess.SubprocessError, zipfile.BadZipFile, BackupError) as error:
        logger.error("Backup %s failed: %s", record.pk, error, exc_info=True)
        partial.unlink(missing_ok=True)
        record.status, record.error = Status.FAILED, str(error)[:1000] or type(error).__name__
        record.finished_at = timezone.now()
        record.save()
        _alert_superusers(record)
        return
    record.status, record.size_bytes, record.finished_at = Status.OK, backup_path(record).stat().st_size, timezone.now()
    record.save()
    logger.info("Backup %s done: %s (%s bytes)", record.pk, record.file_name, record.size_bytes)
    apply_retention()


def _alert_superusers(record):
    message = f"The {record.get_kind_display().lower()} backup failed: {record.error}"
    for admin in get_user_model().objects.filter(is_superuser=True, is_active=True):
        notify(admin, "Backup failed", message, link="/backups/")


def _dump_database(target):
    database = settings.DATABASES["default"]
    engine = database["ENGINE"]
    if "sqlite3" in engine:
        # Plain SQL text (works inside a transaction too). SQLite is for developer PCs and tests only.
        connection.ensure_connection()
        with open(target, "w", encoding="utf-8") as dump_file:
            for line in connection.connection.iterdump():
                dump_file.write(line + "\n")
    elif "postgresql" in engine:
        command = [
            "pg_dump", "--host", database["HOST"] or "localhost", "--port", str(database["PORT"] or 5432),
            "--username", database["USER"], "--no-owner", "--no-privileges", "--clean", "--if-exists",
            "--file", str(target), database["NAME"],
        ]
        result = subprocess.run(
            command, env={**os.environ, "PGPASSWORD": database["PASSWORD"]},
            capture_output=True, text=True, timeout=DUMP_TIMEOUT_SECONDS, check=False,
        )
        if result.returncode != 0:
            raise BackupError(f"pg_dump failed: {result.stderr.strip()[:500]}")
    else:
        raise BackupError(f"Backups are not set up for the database type {engine}.")


def _build_zip(target):
    """database.sql + private_media/... + README.txt in one zip."""
    dump_name = "database.sql"
    media_root = Path(settings.MEDIA_ROOT)
    with tempfile.TemporaryDirectory() as work_folder:
        dump = Path(work_folder) / dump_name
        _dump_database(dump)
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(dump, dump_name)
            if media_root.is_dir():
                for file in media_root.rglob("*"):
                    if file.is_file():
                        archive.write(file, f"private_media/{file.relative_to(media_root).as_posix()}")
            archive.writestr(
                "README.txt",
                f"Backup made {timezone.localtime():%d-%m-%Y %H:%M} on the {settings.ENVIRONMENT} server.\n"
                f"Contains the database ({dump_name}) and the uploaded files (private_media/).\n"
                "Restore on the server with docker/restore_backup.sh. This file holds ALL company data: keep it safe.\n",
            )


def files_to_keep(records, daily, weekly):
    """Which finished backups to keep: the newest `daily`, plus the newest of each of the next `weekly` weeks.

    `records` are newest first. Example: 14 daily + 8 weekly = about 2 months of history.
    """
    keep = list(records[:daily])
    weeks_kept = set()
    for record in records[daily:]:
        week = timezone.localtime(record.created_at).isocalendar()[:2]
        if week not in weeks_kept and len(weeks_kept) < weekly:
            weeks_kept.add(week)
            keep.append(record)
    return keep


def apply_retention():
    """Delete the files of backups outside the keep rules. Their rows stay, marked Removed, with the download history."""
    finished = list(BackupRecord.objects.filter(status=Status.OK))
    keep_ids = {record.pk for record in files_to_keep(finished, settings.BACKUP_KEEP_DAILY, settings.BACKUP_KEEP_WEEKLY)}
    for record in finished:
        if record.pk in keep_ids:
            continue
        try:
            backup_path(record).unlink(missing_ok=True)
        except OSError as error:
            logger.error("Could not delete old backup %s: %s", record.file_name, error)
            continue
        record.status = Status.REMOVED
        record.save(update_fields=["status"])
        logger.info("Old backup removed: %s", record.file_name)


def downloadable_file(record):
    """The zip on disk, or None if it is not a finished backup or the file is gone."""
    if record.status != Status.OK or not record.file_name:
        return None
    path = backup_path(record)
    return path if path.is_file() else None


def record_download(user, record):
    """Note who downloaded the file and when (the history keeps every download)."""
    record.last_downloaded_by = user
    record.last_downloaded_at = timezone.now()
    record.save(update_fields=["last_downloaded_by", "last_downloaded_at"])
    logger.info("Backup %s downloaded by user %s", record.file_name, user.pk)
