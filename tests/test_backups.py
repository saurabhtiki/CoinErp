"""Core Step 11, Part B: backup zip, retention, daily job, superuser-only page, download log."""
import sqlite3
import zipfile
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.utils import timezone
from django_q.models import Schedule

from core.backups import services
from core.backups.models import BackupRecord
from core.masters.models import Company
from core.notifications.models import Notification

User = get_user_model()
Status = BackupRecord.Status


@pytest.fixture(autouse=True)
def folders(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.BACKUP_ROOT = tmp_path / "backups"
    settings.MEDIA_ROOT.mkdir()


@pytest.fixture(autouse=True)
def no_2fa_prompt(monkeypatch):
    """Superusers must pass 2FA before any page; these tests are about backups, not 2FA."""
    monkeypatch.setattr("core.accounts.middleware.roles_require_2fa", lambda user: False)


def make_user(email, superuser=False):
    return User.objects.create_user(email=email, password="a-long-password-123", first_name=email.split("@")[0],
                                    is_superuser=superuser)


@pytest.fixture
def boss():
    return make_user("boss@example.com", superuser=True)


# --- Making a backup -----------------------------------------------------------------------


@pytest.mark.django_db
def test_backup_zip_has_the_database_and_the_uploaded_files(settings, boss):
    Company.objects.create(name="Acme", code="ACME")
    (settings.MEDIA_ROOT / "tasks").mkdir()
    (settings.MEDIA_ROOT / "tasks" / "proof.pdf").write_bytes(b"%PDF-1.4 proof")

    record = services.start_backup(boss)  # tests run jobs at once

    record.refresh_from_db()
    assert record.status == Status.OK and record.kind == BackupRecord.Kind.MANUAL
    assert record.size_bytes > 0
    path = services.backup_path(record)
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        assert {"database.sql", "private_media/tasks/proof.pdf", "README.txt"} <= set(names)
        assert archive.read("private_media/tasks/proof.pdf") == b"%PDF-1.4 proof"
        dump_text = archive.read("database.sql").decode("utf-8")
    restored = sqlite3.connect(":memory:")
    try:
        restored.executescript(dump_text)
        assert restored.execute("select name from masters_company where code = 'ACME'").fetchone() == ("Acme",)
    finally:
        restored.close()


@pytest.mark.django_db
def test_a_failed_backup_is_saved_and_the_superusers_are_told(boss, monkeypatch):
    def broken_dump(target):
        raise services.BackupError("pg_dump failed: disk full")

    monkeypatch.setattr(services, "_dump_database", broken_dump)

    record = services.start_backup()

    record.refresh_from_db()
    assert record.status == Status.FAILED and "disk full" in record.error
    assert not list(services.backup_folder().glob("*.partial"))
    assert Notification.objects.filter(user=boss, title="Backup failed").exists()


@pytest.mark.django_db
def test_second_backup_is_refused_while_one_is_running(boss):
    BackupRecord.objects.create(status=Status.RUNNING)
    with pytest.raises(ValidationError, match="already running"):
        services.start_backup(boss)


@pytest.mark.django_db
def test_a_stuck_old_running_backup_does_not_block_new_ones(boss):
    stuck = BackupRecord.objects.create(status=Status.RUNNING)
    BackupRecord.objects.filter(pk=stuck.pk).update(created_at=timezone.now() - timedelta(hours=3))
    assert services.start_backup(boss).pk != stuck.pk


# --- Keeping 14 daily + 8 weekly -----------------------------------------------------------


def old_backup(days_ago):
    record = BackupRecord.objects.create(status=Status.OK, file_name=f"old-{days_ago}.zip")
    BackupRecord.objects.filter(pk=record.pk).update(created_at=timezone.now() - timedelta(days=days_ago))
    services.backup_path(record).write_bytes(b"zip")
    return record


@pytest.mark.django_db
def test_retention_keeps_newest_daily_plus_one_per_week(settings):
    settings.BACKUP_KEEP_DAILY, settings.BACKUP_KEEP_WEEKLY = 3, 2
    records = [old_backup(days) for days in (0, 1, 2, 10, 11, 12, 20, 21, 50)]

    services.apply_retention()

    status = {record.file_name: BackupRecord.objects.get(pk=record.pk).status for record in records}
    kept = {name for name, state in status.items() if state == Status.OK}
    assert {"old-0.zip", "old-1.zip", "old-2.zip"} <= kept  # the newest 3
    assert len(kept) == 5  # + one backup for each of 2 older weeks
    for record in records:
        on_disk = services.backup_path(record).exists()
        assert on_disk == (status[record.file_name] == Status.OK)  # removed rows lose their file
    assert status["old-50.zip"] == Status.REMOVED


# --- Daily job -----------------------------------------------------------------------------


@pytest.mark.django_db
def test_setup_backup_jobs_schedules_2am_and_keeps_the_running_schedule():
    call_command("setup_backup_jobs")
    job = Schedule.objects.get(name="backups: daily backup")
    assert timezone.localtime(job.next_run).hour == 2 and job.func == "core.backups.services.scheduled_backup"

    next_run = job.next_run
    call_command("setup_backup_jobs")  # again, e.g. after a restart
    assert Schedule.objects.filter(name="backups: daily backup").count() == 1
    assert Schedule.objects.get(name="backups: daily backup").next_run == next_run


@pytest.mark.django_db
def test_scheduled_backup_makes_a_daily_record():
    services.scheduled_backup()
    record = BackupRecord.objects.get()
    assert record.kind == BackupRecord.Kind.AUTO and record.status == Status.OK


# --- Backups page --------------------------------------------------------------------------


@pytest.mark.django_db
def test_only_a_superuser_can_open_the_backups_page(client, boss):
    client.force_login(make_user("pat@example.com"))
    assert client.get("/backups/").status_code == 404
    assert client.post("/backups/now/").status_code == 404
    assert BackupRecord.objects.count() == 0

    client.force_login(boss)
    assert client.get("/backups/").status_code == 200


@pytest.mark.django_db
def test_backups_page_needs_login(client):
    assert client.get("/backups/").status_code == 302


@pytest.mark.django_db
def test_backup_now_button_makes_a_backup(client, boss):
    client.force_login(boss)
    assert client.post("/backups/now/").status_code == 302
    assert BackupRecord.objects.get().status == Status.OK
    assert b"Download .zip" in client.get("/backups/").content


@pytest.mark.django_db
def test_download_gives_the_zip_and_is_logged(client, boss):
    record = services.start_backup(boss)
    record.refresh_from_db()
    client.force_login(boss)

    response = client.get(f"/backups/{record.pk}/download/")

    assert response.status_code == 200
    assert response["Content-Disposition"].startswith("attachment")
    assert b"".join(response.streaming_content).startswith(b"PK")  # a zip file
    record.refresh_from_db()
    assert record.last_downloaded_by == boss and record.last_downloaded_at
    assert record.history.filter(last_downloaded_by=boss).exists()


@pytest.mark.django_db
def test_other_users_cannot_download_and_it_is_not_logged(client, boss):
    record = services.start_backup(boss)
    client.force_login(make_user("pat@example.com"))

    assert client.get(f"/backups/{record.pk}/download/").status_code == 404
    record.refresh_from_db()
    assert record.last_downloaded_at is None


@pytest.mark.django_db
def test_download_of_a_removed_or_missing_file_is_404(client, boss):
    record = services.start_backup(boss)
    record.refresh_from_db()
    services.backup_path(record).unlink()
    client.force_login(boss)
    assert client.get(f"/backups/{record.pk}/download/").status_code == 404
