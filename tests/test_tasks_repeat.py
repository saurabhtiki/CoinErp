"""Tasks app (Phase T2): repeating rules, their dates, the daily job, holidays and off Saturdays."""
from datetime import date
from itertools import islice
from types import SimpleNamespace

import pytest
from django.core import mail
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.utils import timezone
from django_q.models import Schedule

from apps.tasks import services
from apps.tasks.models import Holiday, RecurringTask, Task
from apps.tasks.schedule import OffDays, describe, periods
from core.notifications.models import Notification
from tests.test_tasks import HTMX, acme, globex, make_user, people, private_folder  # noqa: F401  shared fixtures

# November 2026: Sundays 1, 8, 15, 22, 29. Saturdays 7, 14 (2nd), 21, 28 (4th).
USUAL = OffDays()


def rule_of(frequency, start, **extra):
    """A rule for the date maths only (not saved)."""
    fields = {
        "frequency": frequency, "repeat_every": 1, "weekday": None, "due_day": None, "due_month": None,
        "due_in_next_period": False, "off_day_rule": "previous", "start_date": start, "end_date": None, **extra,
    }
    return SimpleNamespace(**fields)


def first(rule, count, off_days=USUAL):
    return [(period.label, period.due) for period in islice(periods(rule, off_days), count)]


# --- Dates -----------------------------------------------------------------------------


def test_monthly_day_20_of_next_month():
    rule = rule_of("monthly", date(2026, 10, 1), due_day=20, due_in_next_period=True)

    # 20 Dec 2026 is a Sunday -> previous working day is Sat 19 Dec (a 3rd Saturday, so a working day)
    assert first(rule, 2) == [("Oct 2026", date(2026, 11, 20)), ("Nov 2026", date(2026, 12, 19))]
    rule.off_day_rule = "next"
    assert first(rule, 2)[1] == ("Nov 2026", date(2026, 12, 21))
    assert describe(rule) == "Every month on day 20 of the next month"


def test_weekly_friday():
    rule = rule_of("weekly", date(2026, 11, 16), weekday=4)

    assert first(rule, 2) == [("Week of 16 Nov 2026", date(2026, 11, 20)), ("Week of 23 Nov 2026", date(2026, 11, 27))]
    assert describe(rule) == "Every week on Friday"


def test_yearly_30_june_starts_with_the_first_date_after_the_start():
    rule = rule_of("yearly", date(2026, 11, 16), due_day=30, due_month=6)

    assert first(rule, 2) == [("2027", date(2027, 6, 30)), ("2028", date(2028, 6, 30))]


def test_every_3_months_and_last_day_of_a_short_month():
    quarterly = rule_of("monthly", date(2026, 10, 1), repeat_every=3, due_day=31, due_in_next_period=True,
                        off_day_rule="keep")
    assert first(quarterly, 2) == [("Oct-Dec 2026", date(2027, 1, 31)), ("Jan-Mar 2027", date(2027, 4, 30))]

    monthly = rule_of("monthly", date(2027, 2, 1), due_day=31, off_day_rule="keep")
    assert first(monthly, 1) == [("Feb 2027", date(2027, 2, 28))]
    assert describe(monthly) == "Every month on the last day"


def test_daily_rule_skips_sundays_off_saturdays_and_holidays():
    rule = rule_of("daily", date(2026, 11, 13))
    off_days = OffDays(holidays=frozenset({date(2026, 11, 17)}))

    days = [due for _, due in first(rule, 3, off_days)]

    assert days == [date(2026, 11, 13), date(2026, 11, 16), date(2026, 11, 18)]


def test_due_date_on_an_off_day_moves_to_a_working_day():
    rule = rule_of("monthly", date(2026, 11, 1), due_day=14)  # Sat 14 Nov 2026 is a 2nd Saturday
    holiday_on_friday = OffDays(holidays=frozenset({date(2026, 11, 13)}))

    assert first(rule, 1, holiday_on_friday)[0][1] == date(2026, 11, 12)
    rule.off_day_rule = "next"
    assert first(rule, 1, holiday_on_friday)[0][1] == date(2026, 11, 16)
    rule.off_day_rule = "keep"
    assert first(rule, 1)[0][1] == date(2026, 11, 14)
    rule.off_day_rule = "previous"
    assert first(rule, 1, OffDays(saturdays=frozenset()))[0][1] == date(2026, 11, 14)  # no Saturday is off


def test_no_period_after_the_end_date():
    rule = rule_of("monthly", date(2026, 10, 1), due_day=10, end_date=date(2026, 11, 30))

    assert [label for label, _ in first(rule, 5)] == ["Oct 2026", "Nov 2026"]


# --- The daily job ---------------------------------------------------------------------


@pytest.fixture
def gstr1(people, acme):
    """GSTR1: every month, due on the 11th of the next month, shown 7 days before."""
    rule = services.save_rule(
        people["saurabh"], acme, title="GSTR1", owner=people["het"], reviewer=people["amar"],
        collaborators=[people["ghosh"]], frequency="monthly", due_day=11, due_in_next_period=True,
        off_day_rule="previous", create_days_before=7, start_date=date(2026, 10, 1),
    )
    services.add_rule_action(people["saurabh"], rule, "Send data to CA", people["amar"], days_before_due=3)
    return rule


@pytest.mark.django_db
def test_job_makes_the_task_some_days_before_and_copies_the_team(people, gstr1):
    assert services.create_due_tasks(today=date(2026, 11, 3)) == 0  # due 11 Nov, shown from 4 Nov
    mail.outbox.clear()

    assert services.create_due_tasks(today=date(2026, 11, 4)) == 1

    task = Task.objects.get(recurring_task=gstr1)
    assert (task.title, task.due_date, task.period_label) == ("GSTR1 - Oct 2026", date(2026, 11, 11), "Oct 2026")
    assert (task.owner, task.reviewer, task.created_by) == (people["het"], people["amar"], people["saurabh"])
    assert list(task.collaborators.all()) == [people["ghosh"]]
    action = task.actions.get()
    assert (action.title, action.owner, action.due_date) == ("Send data to CA", people["amar"], date(2026, 11, 8))
    assert Notification.objects.filter(user=people["het"], title__contains="GSTR1 - Oct 2026").exists()
    assert mail.outbox == []  # bell only


@pytest.mark.django_db
def test_job_never_makes_the_same_task_twice_and_catches_up_missed_days(gstr1):
    assert services.create_due_tasks(today=date(2026, 11, 4)) == 1
    assert services.create_due_tasks(today=date(2026, 11, 4)) == 0
    assert services.create_due_tasks(today=date(2026, 11, 5)) == 0

    # the job did not run for two months: Nov (due 11 Dec) and Dec (due 11 Jan) are still made
    assert services.create_due_tasks(today=date(2027, 1, 5)) == 2
    assert sorted(Task.objects.values_list("period_label", flat=True)) == ["Dec 2026", "Nov 2026", "Oct 2026"]
    assert sorted(Task.objects.values_list("number", flat=True)) == [1, 2, 3]


@pytest.mark.django_db
def test_paused_and_ended_rules_make_nothing(people, gstr1):
    services.set_paused(people["saurabh"], gstr1, True)
    assert services.create_due_tasks(today=date(2026, 11, 4)) == 0

    services.set_paused(people["saurabh"], gstr1, False)
    gstr1.end_date = date(2026, 10, 31)
    gstr1.save()
    assert services.create_due_tasks(today=date(2026, 11, 4)) == 0


@pytest.mark.django_db
def test_one_broken_rule_does_not_stop_the_others(people, acme, gstr1, monkeypatch):
    services.save_rule(people["saurabh"], acme, title="Broken", owner=people["het"], frequency="monthly",
                       due_day=11, due_in_next_period=True, start_date=date(2026, 10, 1))
    real = services._make_task

    def sometimes_fails(rule, period):
        if rule.title == "Broken":
            raise RuntimeError("something went wrong")
        return real(rule, period)

    monkeypatch.setattr(services, "_make_task", sometimes_fails)

    assert services.create_due_tasks(today=date(2026, 11, 4)) == 1
    assert Task.objects.get().title == "GSTR1 - Oct 2026"


@pytest.mark.django_db
def test_changing_a_rule_touches_only_future_tasks(people, gstr1):
    services.create_due_tasks(today=date(2026, 11, 4))

    services.save_rule(people["saurabh"], gstr1.company, gstr1, owner=people["amar"], reviewer=None)
    services.create_due_tasks(today=date(2026, 12, 4))

    owners = dict(Task.objects.values_list("period_label", "owner__first_name"))
    assert owners == {"Oct 2026": "het", "Nov 2026": "amar"}


@pytest.mark.django_db
def test_new_timing_starts_today_and_does_not_fill_the_past(people, gstr1):
    services.save_rule(people["saurabh"], gstr1.company, gstr1, frequency="weekly", weekday=4)
    gstr1.refresh_from_db()

    assert (gstr1.start_date, gstr1.skip_before) == (date(2026, 10, 1), timezone.localdate())
    assert (gstr1.due_day, gstr1.weekday) == (None, 4)
    first_period = next(iter(periods(gstr1, services.off_days_of(gstr1.company))))
    assert first_period.due >= timezone.localdate()


@pytest.mark.django_db
def test_changing_a_quarterly_rule_keeps_its_quarters_and_still_makes_the_new_period(people, acme):
    rule = services.save_rule(people["saurabh"], acme, title="TDS return", owner=people["het"], frequency="monthly",
                              due_day=31, due_in_next_period=True, start_date=date(2026, 10, 1))
    services.create_due_tasks(today=date(2026, 11, 30))  # makes "Oct 2026", which starts on 1 Oct

    services.save_rule(people["saurabh"], acme, rule, repeat_every=3)  # now every quarter
    rule.skip_before = date(2026, 12, 1)  # as if the change was made on 1 Dec 2026
    rule.save()
    services.create_due_tasks(today=date(2027, 1, 31))

    # the quarter still begins in October, and it is made although a task starting 1 Oct already exists
    assert sorted(Task.objects.values_list("period_label", flat=True)) == ["Oct 2026", "Oct-Dec 2026"]


@pytest.mark.django_db
def test_long_rule_title_keeps_the_period_and_view_only_people_get_no_pause_button(people, gstr1, client):
    gstr1.title = "G" * 200
    gstr1.save()
    services.create_due_tasks(today=date(2026, 11, 4))
    title = Task.objects.get().title
    assert title.endswith(" - Oct 2026") and len(title) == 200

    client.force_login(people["ghosh"])  # collaborator: sees the rule, cannot change it
    assert f"/tasks/repeating/{gstr1.pk}/pause/" not in client.get("/tasks/repeating/").content.decode()
    client.force_login(people["het"])
    assert f"/tasks/repeating/{gstr1.pk}/pause/" in client.get("/tasks/repeating/").content.decode()


@pytest.mark.django_db
def test_rule_needs_the_fields_of_its_frequency(people, acme):
    with pytest.raises(ValidationError) as error:
        services.save_rule(people["saurabh"], acme, title="Stock audit", owner=people["het"], frequency="yearly")
    assert set(error.value.message_dict) == {"due_day", "due_month"}

    with pytest.raises(ValidationError):
        services.save_rule(people["saurabh"], acme, title="Bank reco", owner=people["het"], frequency="weekly")


# --- Who sees and changes what ---------------------------------------------------------


@pytest.mark.django_db
def test_who_sees_and_changes_a_rule(people, gstr1, client):
    for name in ("saurabh", "het", "amar", "ghosh", "foram", "boss"):
        assert services.visible_rules(people[name]).filter(pk=gstr1.pk).exists(), name
    assert not services.visible_rules(people["outsider"]).exists()

    client.force_login(people["outsider"])
    assert client.get(f"/tasks/repeating/{gstr1.pk}/").status_code == 404

    with pytest.raises(PermissionDenied):  # a collaborator only views
        services.set_paused(people["ghosh"], gstr1, True)
    services.set_paused(people["foram"], gstr1, True)  # the owner's manager may
    assert RecurringTask.objects.get().is_paused


@pytest.mark.django_db
def test_other_company_user_cannot_open_a_rule(gstr1, globex, client):
    gita = make_user("gita", [globex], admin=True)
    client.force_login(gita)

    assert client.get(f"/tasks/repeating/{gstr1.pk}/").status_code == 404
    assert not services.visible_rules(gita).exists()


@pytest.mark.django_db
def test_only_the_admin_keeps_holidays_and_off_saturdays(people, acme, globex):
    with pytest.raises(PermissionDenied):
        services.add_holiday(people["het"], acme, date(2026, 11, 9), "Diwali")
    with pytest.raises(PermissionDenied):
        services.set_off_saturdays(people["het"], acme, [1])

    holiday = services.add_holiday(people["boss"], acme, date(2026, 11, 9), "Diwali")
    with pytest.raises(ValidationError):
        services.add_holiday(people["boss"], acme, date(2026, 11, 9), "Diwali again")
    services.set_off_saturdays(people["boss"], acme, ["1", "3"])

    assert list(services.holidays_for(people["het"])) == [holiday]  # everyone with Tasks sees them
    assert not services.holidays_for(make_user("gita", [globex])).exists()
    off_days = services.off_days_of(acme)
    assert off_days.saturdays == {1, 3} and off_days.holidays == {date(2026, 11, 9)}
    assert services.off_days_of(globex).saturdays == {2, 4}  # the usual ones until an admin changes them

    with pytest.raises(PermissionDenied):
        services.remove_holiday(people["het"], holiday)
    services.remove_holiday(people["boss"], holiday)
    assert not Holiday.objects.exists()


@pytest.mark.django_db
def test_job_uses_the_company_holidays(people, acme, gstr1):
    services.add_holiday(people["boss"], acme, date(2026, 11, 11), "Special day")

    services.create_due_tasks(today=date(2026, 11, 10))

    assert Task.objects.get().due_date == date(2026, 11, 10)  # moved to the previous working day


@pytest.mark.django_db
def test_only_the_admin_can_create_due_tasks_now(people, gstr1, client):
    with pytest.raises(PermissionDenied):
        services.create_due_tasks(user=people["het"])

    client.force_login(people["het"])
    page = client.get("/tasks/repeating/")
    assert "Create due tasks now" not in page.content.decode()
    client.post("/tasks/repeating/run/")
    assert not Task.objects.exists()

    client.force_login(people["boss"])
    assert "Create due tasks now" in client.get("/tasks/repeating/").content.decode()
    response = client.post("/tasks/repeating/run/", follow=True)
    assert Task.objects.filter(recurring_task=gstr1).exists()  # GSTR1 started on 1 Oct 2026, so tasks are due
    assert "created." in response.content.decode()


# --- Screens ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_rule_screens(people, acme, gstr1, client):
    client.force_login(people["saurabh"])

    page = client.get("/tasks/repeating/").content.decode()
    assert "GSTR1" in page and "Every month on day 11 of the next month" in page

    panel = client.get(f"/tasks/repeating/{gstr1.pk}/", **HTMX).content.decode()
    assert "Send data to CA" in panel and "Save changes" in panel

    new_form = client.get("/tasks/repeating/new/", **HTMX).content.decode()
    assert 'name="due_date"' not in new_form  # a rule has no due date of its own
    assert 'name="due_day"' in new_form

    viewer = client
    viewer.force_login(people["ghosh"])
    assert "Save changes" not in viewer.get(f"/tasks/repeating/{gstr1.pk}/", **HTMX).content.decode()


@pytest.mark.django_db
def test_create_a_rule_from_the_form_and_preview_its_dates(people, acme, client):
    client.force_login(people["saurabh"])
    fields = {
        "company": acme.pk, "title": "Bank reco", "owner": people["het"].pk, "priority": "medium",
        "frequency": "weekly", "repeat_every": 1, "weekday": 4, "off_day_rule": "previous", "create_days_before": 3,
        "start_date": "2027-01-04",
    }

    preview = client.post("/tasks/repeating/preview/", fields, **HTMX).content.decode()
    assert preview == "First task: Fri 08 Jan 2027 (Week of 04 Jan 2027), then 15 Jan 2027, 22 Jan 2027"

    past = client.post("/tasks/repeating/preview/", {**fields, "start_date": "2026-11-02"}, **HTMX).content.decode()
    assert "earlier task" in past  # a start date in the past is said openly
    assert "earlier task" not in client.post(
        "/tasks/repeating/preview/", {**fields, "start_date": "2026-11-02", "saved": "1"}, **HTMX
    ).content.decode()

    missing_day = client.post("/tasks/repeating/preview/", {**fields, "frequency": "monthly"}, **HTMX).content.decode()
    assert "Pick the day of the month" in missing_day

    response = client.post("/tasks/repeating/new/", fields, **HTMX)
    rule = RecurringTask.objects.get()
    assert response.status_code == 200
    assert (rule.title, rule.owner, rule.weekday, rule.created_by) == ("Bank reco", people["het"], 4, people["saurabh"])

    client.post(f"/tasks/repeating/{rule.pk}/actions/", {"title": "Get statement", "owner": people["amar"].pk, "days_before_due": 1}, **HTMX)
    assert rule.actions.get().title == "Get statement"
    client.post(f"/tasks/repeating/{rule.pk}/pause/", {"from": "list"}, **HTMX)
    assert RecurringTask.objects.get().is_paused


@pytest.mark.django_db
def test_task_made_by_a_rule_shows_where_it_comes_from(people, gstr1, client):
    services.create_due_tasks(today=date(2026, 11, 4))
    client.force_login(people["het"])

    panel = client.get(f"/tasks/{Task.objects.get().pk}/", **HTMX).content.decode()

    assert "Repeats: Every month on day 11 of the next month" in panel


@pytest.mark.django_db
def test_holiday_screen(people, acme, client):
    client.force_login(people["het"])
    assert "Add a holiday" not in client.get("/tasks/holidays/").content.decode()
    client.post("/tasks/holidays/", {"company": acme.pk, "date": "2026-11-09", "name": "Diwali"})
    assert not Holiday.objects.exists()

    client.force_login(people["boss"])
    assert "Add a holiday" in client.get("/tasks/holidays/").content.decode()
    client.post("/tasks/holidays/", {"company": acme.pk, "date": "2026-11-09", "name": "Diwali"})
    holiday = Holiday.objects.get()
    page = client.get("/tasks/holidays/").content.decode()
    assert "Diwali" in page and f"/tasks/holidays/{holiday.pk}/remove/" in page

    client.post("/tasks/holidays/saturdays/", {"company": acme.pk, "saturdays": ["1", "2", "3", "4", "5"]})
    assert services.off_saturdays_of(acme) == [1, 2, 3, 4, 5]

    client.force_login(people["het"])
    assert f"/tasks/holidays/{holiday.pk}/remove/" not in client.get("/tasks/holidays/").content.decode()
    client.post(f"/tasks/holidays/{holiday.pk}/remove/")
    assert Holiday.objects.exists()


@pytest.mark.django_db
def test_daily_job_is_scheduled_once():
    call_command("setup_task_jobs")
    call_command("setup_task_jobs")

    job = Schedule.objects.get()
    assert (job.func, job.schedule_type) == ("apps.tasks.services.create_due_tasks", Schedule.DAILY)


@pytest.mark.django_db
def test_resume_does_not_fill_the_paused_period(people, gstr1):
    services.set_paused(people["saurabh"], gstr1, True)
    services.set_paused(people["saurabh"], gstr1, False)
    assert gstr1.skip_before == timezone.localdate()
