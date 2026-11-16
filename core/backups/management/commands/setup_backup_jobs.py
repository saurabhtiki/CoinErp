"""Adds the daily backup job. Safe to run again (docker/entrypoint.sh runs it at every start).

    uv run python manage.py setup_backup_jobs
"""
from datetime import datetime, time, timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone
from django_q.models import Schedule

JOB_NAME = "backups: daily backup"
JOB_FUNCTION = "core.backups.services.scheduled_backup"
RUN_AT = time(2, 0)  # 2:00 at night, when nobody is working


class Command(BaseCommand):
    help = "Schedule the daily backup (every day at 2:00 am)."

    def handle(self, *args, **options):
        now = timezone.localtime()
        next_run = timezone.make_aware(datetime.combine(now.date(), RUN_AT))
        if next_run <= now:
            next_run += timedelta(days=1)
        job = Schedule.objects.filter(name=JOB_NAME).first()
        if job:  # keep the running schedule: a restart must not push tonight's backup to tomorrow
            job.func, job.schedule_type = JOB_FUNCTION, Schedule.DAILY
            job.save()
            self.stdout.write(f"Daily backup already scheduled: next run {job.next_run:%d %b %Y %H:%M}.")
            return
        Schedule.objects.create(name=JOB_NAME, func=JOB_FUNCTION, schedule_type=Schedule.DAILY, next_run=next_run)
        self.stdout.write(f"Daily backup added: next run {next_run:%d %b %Y %H:%M}.")
