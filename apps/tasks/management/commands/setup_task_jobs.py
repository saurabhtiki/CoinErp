"""Adds the daily Tasks jobs. Safe to run again (each job is kept once, by name).

    uv run python manage.py setup_task_jobs

- 6:00 am: make tasks from repeating rules.
- 7:00 am: the morning email (due today, overdue, waiting for review).
"""
from datetime import datetime, time, timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone
from django_q.models import Schedule

JOBS = (
    ("tasks: create due tasks", "apps.tasks.services.create_due_tasks", time(6, 0)),
    ("tasks: daily email", "apps.tasks.services.send_daily_digest", time(7, 0)),
)


class Command(BaseCommand):
    help = "Schedule the daily Tasks jobs: repeating tasks at 6:00 am, the morning email at 7:00 am."

    def handle(self, *args, **options):
        now = timezone.localtime()
        for name, function, run_at in JOBS:
            # Today's run if its time has not come yet: a deploy at 3:00 am must not skip today's jobs.
            next_run = timezone.make_aware(datetime.combine(now.date(), run_at))
            if next_run <= now:
                next_run += timedelta(days=1)
            _, created = Schedule.objects.update_or_create(
                name=name, defaults={"func": function, "schedule_type": Schedule.DAILY, "next_run": next_run}
            )
            self.stdout.write(f"{name}: {'added' if created else 'updated'}, next run {next_run:%d %b %Y %H:%M}.")
