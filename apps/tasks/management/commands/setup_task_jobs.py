"""Adds the daily job that makes tasks from repeating rules. Safe to run again.

    uv run python manage.py setup_task_jobs
"""
from datetime import datetime, time, timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone
from django_q.models import Schedule

JOB_NAME = "tasks: create due tasks"
JOB_FUNCTION = "apps.tasks.services.create_due_tasks"
RUN_AT = time(6, 0)  # 6:00 in the morning, before people start work


class Command(BaseCommand):
    help = "Schedule the daily job that makes tasks from repeating rules (every day at 6:00 am)."

    def handle(self, *args, **options):
        tomorrow = timezone.localdate() + timedelta(days=1)
        next_run = timezone.make_aware(datetime.combine(tomorrow, RUN_AT))
        _, created = Schedule.objects.update_or_create(
            name=JOB_NAME, defaults={"func": JOB_FUNCTION, "schedule_type": Schedule.DAILY, "next_run": next_run}
        )
        self.stdout.write(f"Daily job {'added' if created else 'updated'}: next run {next_run:%d %b %Y %H:%M}.")
