"""Tasks app (Phase T3, Part C): the 7:00 am email lists due today, overdue and waiting for review."""
from datetime import date, timedelta

import pytest
from django.core import mail
from django.core.management import call_command
from django.utils import timezone
from django_q.models import Schedule

from apps.tasks import services
from apps.tasks.models import Task
from core.accounts.models import CompanyRole
from core.notifications.models import NotificationLog
from tests.test_tasks import acme, globex, make_user, people  # noqa: F401  shared fixtures

Status = Task.Status
TODAY = date(2026, 11, 17)  # a Tuesday
SUNDAY = date(2026, 11, 15)


def add(people, company, owner="het", due=TODAY, by="saurabh", status=None, **extra):
    fields = {"title": "GSTR1", "owner": people[owner] if isinstance(owner, str) else owner, "due_date": due, **extra}
    task = services.create_task(people[by] if isinstance(by, str) else by, company, **fields)
    if status:
        Task.objects.filter(pk=task.pk).update(status=status)
    return task


def mail_to(email):
    return [message for message in mail.outbox if message.to == [email]]


@pytest.mark.django_db
def test_digest_lists_due_today_overdue_and_review(people, acme):
    today = add(people, acme, title="Today")
    late = add(people, acme, title="Late", due=TODAY - timedelta(days=3))
    add(people, acme, title="Later", due=TODAY + timedelta(days=2))
    add(people, acme, title="Done late", due=TODAY - timedelta(days=3), status=Status.COMPLETED)
    add(people, acme, title="Not mine", owner="amar", reviewer=people["het"])  # not under review yet
    check = add(people, acme, title="Check", owner="amar", reviewer=people["het"], status=Status.UNDER_REVIEW)

    lists = services.digest_for(people["het"], TODAY)

    assert lists == {"today": [today], "overdue": [late], "review": [check]}


@pytest.mark.django_db
def test_one_email_per_person_with_links(people, acme):
    task = add(people, acme, title="GSTR1 Oct")
    add(people, acme, title="TDS", due=TODAY - timedelta(days=1))
    mail.outbox.clear()

    assert services.send_daily_digest(TODAY) == 1

    [message] = mail_to("het@example.com")
    assert message.subject == "Your tasks for 17 Nov 2026: 1 due today, 1 overdue, 0 to review"
    assert f"{task.code} GSTR1 Oct: http://" in message.body and f"/tasks/{task.pk}/" in message.body
    assert "Overdue (1):" in message.body and "(due 16-11-2026)" in message.body
    assert "Waiting for your review" not in message.body
    log = NotificationLog.objects.get(user=people["het"], title=message.subject)
    assert log.channel == NotificationLog.Channel.EMAIL  # email only, nothing in the bell


@pytest.mark.django_db
def test_nothing_to_show_sends_nothing(people, acme):
    add(people, acme, due=TODAY + timedelta(days=5))
    add(people, acme, due=TODAY - timedelta(days=1), status=Status.COMPLETED)
    mail.outbox.clear()

    assert services.send_daily_digest(TODAY) == 0
    assert mail.outbox == []


@pytest.mark.django_db
def test_no_email_on_sunday_or_holiday(people, acme):
    add(people, acme, due=SUNDAY - timedelta(days=2))
    services.add_holiday(people["boss"], acme, TODAY, "Guru Nanak Jayanti")
    mail.outbox.clear()

    assert services.send_daily_digest(SUNDAY) == 0
    assert services.send_daily_digest(TODAY) == 0
    assert services.send_daily_digest(TODAY + timedelta(days=1)) == 1
    assert len(mail_to("het@example.com")) == 1


@pytest.mark.django_db
def test_holiday_in_one_company_still_sends_if_other_company_works(people, acme, globex):
    CompanyRole.objects.create(user=people["het"], company=globex, role=people["het"].company_roles.first().role)
    services.add_holiday(people["boss"], acme, TODAY, "Guru Nanak Jayanti")
    add(people, acme)
    mail.outbox.clear()

    assert services.send_daily_digest(TODAY) == 1


@pytest.mark.django_db
def test_person_who_lost_access_gets_nothing(people, acme):
    add(people, acme)
    CompanyRole.objects.filter(user=people["het"]).delete()
    mail.outbox.clear()

    assert services.send_daily_digest(TODAY) == 0


@pytest.mark.django_db
def test_one_bad_person_does_not_stop_the_others(people, acme, monkeypatch, caplog):
    add(people, acme, owner="het")
    add(people, acme, owner="amar", by="amar")
    mail.outbox.clear()
    real_digest_for = services.digest_for

    def broken_for_het(user, today=None):
        if user == people["het"]:
            raise RuntimeError("database hiccup")
        return real_digest_for(user, today)

    monkeypatch.setattr(services, "digest_for", broken_for_het)

    assert services.send_daily_digest(TODAY) == 1
    assert mail_to("amar@example.com") and not mail_to("het@example.com")
    assert f"Daily task email for user {people['het'].pk} could not be sent" in caplog.text


@pytest.mark.django_db
def test_setup_command_schedules_each_job_once():
    call_command("setup_task_jobs")
    call_command("setup_task_jobs")

    jobs = dict(Schedule.objects.values_list("name", "func"))
    assert jobs == {
        "tasks: create due tasks": "apps.tasks.services.create_due_tasks",
        "tasks: daily email": "apps.tasks.services.send_daily_digest",
    }
    email_job = Schedule.objects.get(name="tasks: daily email")
    assert (email_job.schedule_type, timezone.localtime(email_job.next_run).hour) == (Schedule.DAILY, 7)
