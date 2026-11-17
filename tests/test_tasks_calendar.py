"""Tasks app (Phase T3, Part B): the calendar shows each task on its due day, only to people who may see it."""
from datetime import date

import pytest

from apps.tasks import services
from apps.tasks.models import Task
from tests.test_tasks import acme, globex, make_user, people  # noqa: F401  shared fixtures

TODAY = date(2026, 11, 17)


def add(people, company, owner="het", due=TODAY, by="saurabh", **extra):
    fields = {"title": "GSTR1", "owner": people[owner] if isinstance(owner, str) else owner, "due_date": due, **extra}
    return services.create_task(people[by] if isinstance(by, str) else by, company, **fields)


def day_of(month, wanted):
    return next(day for week in month["weeks"] for day in week if day["date"] == wanted)


@pytest.mark.django_db
def test_tasks_appear_on_their_due_day(people, acme):
    on_17 = add(people, acme, due=date(2026, 11, 17))
    late = add(people, acme, due=date(2026, 11, 3))
    add(people, acme, due=date(2027, 1, 5))  # another month

    month = services.calendar_month(people["het"], 2026, 11, today=TODAY)

    assert day_of(month, date(2026, 11, 17))["tasks"] == [on_17]
    assert day_of(month, date(2026, 11, 3))["tasks"][0].is_overdue
    assert not day_of(month, date(2026, 11, 17))["tasks"][0].is_overdue
    shown = [task for week in month["weeks"] for day in week for task in day["tasks"]]
    assert set(shown) == {on_17, late}


@pytest.mark.django_db
def test_grid_starts_on_monday_and_covers_the_month(people, acme):
    month = services.calendar_month(people["het"], 2026, 11, today=TODAY)

    assert month["weeks"][0][0]["date"] == date(2026, 10, 26)  # Monday before 1 Nov (a Sunday)
    assert month["weeks"][-1][-1]["date"] == date(2026, 12, 6)
    assert not day_of(month, date(2026, 10, 26))["in_month"]
    assert day_of(month, TODAY)["is_today"]
    assert (month["previous"], month["next"]) == (date(2026, 10, 1), date(2026, 12, 1))


@pytest.mark.django_db
def test_many_tasks_in_a_day_go_under_more(people, acme):
    for _ in range(5):
        add(people, acme)

    today_box = day_of(services.calendar_month(people["het"], 2026, 11, today=TODAY), TODAY)

    assert (len(today_box["tasks"]), len(today_box["more"])) == (3, 2)


@pytest.mark.django_db
def test_sundays_off_saturdays_and_holidays_are_shaded(people, acme):
    services.add_holiday(people["boss"], acme, date(2026, 11, 9), "Diwali")
    month = services.calendar_month(people["het"], 2026, 11, today=TODAY)

    assert day_of(month, date(2026, 11, 15))["off"]  # Sunday
    assert day_of(month, date(2026, 11, 14))["off"]  # 2nd Saturday (default off)
    assert not day_of(month, date(2026, 11, 7))["off"]  # 1st Saturday works
    assert day_of(month, date(2026, 11, 9))["off"] and day_of(month, date(2026, 11, 9))["holidays"] == ["Diwali"]
    assert not day_of(month, date(2026, 11, 10))["off"]


@pytest.mark.django_db
def test_company_off_saturdays_are_used(people, acme):
    services.set_off_saturdays(people["boss"], acme, [1, 3])
    month = services.calendar_month(people["het"], 2026, 11, today=TODAY)

    assert day_of(month, date(2026, 11, 7))["off"]
    assert not day_of(month, date(2026, 11, 14))["off"]


@pytest.mark.django_db
def test_day_is_shaded_only_if_off_in_every_company(people, acme, globex):
    both = make_user("both", [acme, globex])
    services.add_holiday(people["boss"], acme, date(2026, 11, 9), "Diwali")

    nov_9 = day_of(services.calendar_month(both, 2026, 11, today=TODAY), date(2026, 11, 9))

    assert not nov_9["off"]  # Globex works that day
    assert nov_9["holidays"] == ["Diwali"]  # but the name is still shown


@pytest.mark.django_db
def test_mine_shows_only_my_tasks_and_all_shows_what_i_can_see(people, acme):
    mine = add(people, acme, owner="boss", by="boss", reviewer=people["boss"])
    other = add(people, acme, owner="het")

    def shown(mine_only):
        month = services.calendar_month(people["boss"], 2026, 11, mine=mine_only, today=TODAY)
        return set(day_of(month, TODAY)["tasks"])

    assert shown(True) == {mine}
    assert shown(False) == {mine, other}


@pytest.mark.django_db
def test_calendar_never_shows_unseen_or_other_company_tasks(people, acme, globex):
    stranger = make_user("stranger", [globex], admin=True)
    add({"stranger": stranger}, globex, owner=stranger, by=stranger)
    add(people, acme)

    assert not day_of(services.calendar_month(people["outsider"], 2026, 11, today=TODAY), TODAY)["tasks"]
    assert len(day_of(services.calendar_month(stranger, 2026, 11, today=TODAY), TODAY)["tasks"]) == 1


@pytest.mark.django_db
def test_cancelled_task_is_not_shown(people, acme):
    task = add(people, acme)
    Task.objects.filter(pk=task.pk).update(is_active=False)

    assert not day_of(services.calendar_month(people["het"], 2026, 11, today=TODAY), TODAY)["tasks"]


# --- Page -------------------------------------------------------------------------------


@pytest.mark.django_db
def test_calendar_page_shows_month_and_task_links(client, people, acme):
    task = add(people, acme, due=date(2026, 11, 20))
    client.force_login(people["het"])

    page = client.get("/tasks/calendar/?month=2026-11&show=mine")

    text = page.content.decode()
    assert page.status_code == 200
    assert "November 2026" in text
    assert f"/tasks/{task.pk}/" in text
    assert "?month=2026-12&show=mine" in text  # Next keeps the Mine switch


@pytest.mark.django_db
def test_htmx_request_returns_only_the_grid(client, people, acme):
    client.force_login(people["het"])

    page = client.get("/tasks/calendar/?month=2026-12", headers={"HX-Request": "true"})

    text = page.content.decode()
    assert 'id="calendar"' in text and "December 2026" in text
    assert "<html" not in text


@pytest.mark.django_db
def test_bad_month_shows_this_month_with_a_message(client, people, acme):
    client.force_login(people["het"])

    page = client.get("/tasks/calendar/?month=2026-13")

    assert page.status_code == 200
    assert "is not a month like 2026-11" in page.content.decode()


@pytest.mark.django_db
def test_panel_opened_from_calendar_closes_back_to_it(client, people, acme):
    task = add(people, acme)
    client.force_login(people["het"])
    calendar_url = "http://testserver/tasks/calendar/?month=2026-11&show=all"

    page = client.get(f"/tasks/{task.pk}/", headers={"HX-Request": "true", "HX-Current-URL": calendar_url})

    assert page.context["close_url"] == calendar_url
    assert not page.context["as_page"]


@pytest.mark.django_db
def test_calendar_needs_tasks_app(client, people):
    from django.contrib.auth import get_user_model

    no_app = get_user_model().objects.create_user(email="noapp@example.com", password="a-long-password-123")
    client.force_login(no_app)
    assert client.get("/tasks/calendar/").status_code == 403
