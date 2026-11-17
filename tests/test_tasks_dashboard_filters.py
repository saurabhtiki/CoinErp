"""Tasks app (Phase T5, Part A): dashboard filters, and every number opens the tasks it counted."""
from datetime import datetime, timedelta

import pytest
from django.utils import timezone

from apps.tasks import services
from apps.tasks.models import Task
from tests.test_tasks import HTMX, acme, globex, make_user, people, private_folder  # noqa: F401  shared fixtures

Status = Task.Status


def add(by, company, owner, days=0, status=None, **extra):
    """A task due `days` from today."""
    task = services.create_task(
        by, company, title="GSTR1", owner=owner, due_date=timezone.localdate() + timedelta(days=days), **extra
    )
    if status:
        Task.objects.filter(pk=task.pk).update(status=status)
    return task


@pytest.fixture
def boss2(acme, globex):
    """Admin in both companies: sees every task."""
    return make_user("boss2", [acme, globex], admin=True)


@pytest.fixture
def tasks(people, acme, globex, boss2):
    mis = services.categories_of(acme).get(name="MIS")
    return {
        "het_late_high": add(people["saurabh"], acme, people["het"], -2, priority="high", category=mis),
        "het_today": add(people["saurabh"], acme, people["het"], 0),
        "amar_week_blocked": add(people["saurabh"], acme, people["amar"], 3, status=Status.BLOCKED, category=mis),
        "globex_late": add(boss2, globex, boss2, -1, priority="high"),
    }


def rows_at(client, url):
    return {row.pk for row in client.get(url).context["table"].page}


@pytest.mark.django_db
def test_each_filter_narrows_cards_charts_and_people(client, people, acme, globex, boss2, tasks):
    client.force_login(boss2)

    def page(query=""):
        return client.get(f"/tasks/dashboard/{query}").context

    every = page()
    assert every["cards"][0]["count"] == 2  # overdue in both companies
    assert page(f"?company={globex.pk}")["cards"][0]["count"] == 1
    assert page("?priority=high")["cards"][0]["count"] == 2
    assert page(f"?person={people['het'].pk}")["cards"][0]["count"] == 1
    by_mis = page("?category=MIS")
    assert by_mis["charts"]["status"]["labels"] == ["Not Started", "Blocked"]
    assert [row.first_name for row in page(f"?company={globex.pk}")["table"].page] == ["boss2"]
    no_category = page(f"?category={services.NO_CATEGORY}")
    assert sum(no_category["charts"]["status"]["values"]) == 2  # het_today and globex_late


@pytest.mark.django_db
def test_a_filter_the_user_may_not_pick_is_ignored_with_a_message(client, people, acme, globex, tasks):
    client.force_login(people["het"])  # Acme only, and sees only his own tasks

    page = client.get(f"/tasks/dashboard/?company={globex.pk}&person={people['amar'].pk}&priority=high")

    assert page.context["filters"] == {"priority": "high"}
    text = page.content.decode()
    assert "The Company filter was ignored" in text and "The Person filter was ignored" in text
    assert page.context["cards"][0]["count"] == 1  # his own late high task, nothing of Globex or Amar


@pytest.mark.django_db
def test_every_dashboard_number_opens_exactly_the_tasks_it_counted(client, people, acme, boss2, tasks):
    client.force_login(boss2)
    context = client.get(f"/tasks/dashboard/?company={acme.pk}").context

    for card in context["cards"]:
        assert len(rows_at(client, card["url"])) == card["count"], card["label"]
    for chart in context["charts"].values():
        for url, total in zip(chart["urls"], chart["values"]):
            assert len(rows_at(client, url)) == total, url
    het = next(row for row in context["table"].page if row.pk == people["het"].pk)
    links = context["person_urls"]
    assert rows_at(client, f"{links['open']}&person={het.pk}") == {tasks["het_late_high"].pk, tasks["het_today"].pk}
    assert rows_at(client, f"{links['overdue']}&person={het.pk}") == {tasks["het_late_high"].pk}
    assert het.open_count == 2 and het.overdue_count == 1


@pytest.mark.django_db
def test_done_this_month_link_shows_tasks_completed_this_month(client, people, acme, tasks):
    task = tasks["het_today"]
    Task.objects.filter(pk=task.pk).update(status=Status.COMPLETED, completed_at=timezone.now())
    last_month = add(people["saurabh"], acme, people["het"], -40)
    Task.objects.filter(pk=last_month.pk).update(
        status=Status.COMPLETED,
        completed_at=timezone.make_aware(datetime.combine(timezone.localdate().replace(day=1), datetime.min.time()))
        - timedelta(days=1),
    )
    client.force_login(people["foram"])  # Het's manager

    page = client.get(f"/tasks/list/all/?done=month&person={people['het'].pk}")

    assert {row.pk for row in page.context["table"].page} == {task.pk}
    assert "Only: <strong>het, completed this month</strong>" in page.content.decode()


@pytest.mark.django_db
def test_list_keeps_dashboard_filters_on_table_clicks_and_ignores_bad_ones(client, people, acme, globex, tasks):
    client.force_login(people["het"])

    page = client.get(f"/tasks/list/all/?company={acme.pk}&sort=-due_date", HTTP_HX_TARGET="tasks-table", **HTMX)
    assert f"company={acme.pk}" in page.context["table"].url()

    page = client.get(f"/tasks/list/all/?company={globex.pk}")
    assert "The Company filter was ignored" in page.content.decode()
    assert {row.pk for row in page.context["table"].page} == {tasks["het_late_high"].pk, tasks["het_today"].pk}


@pytest.mark.django_db
def test_filter_bar_shows_choices_and_clear(client, people, acme, tasks):
    client.force_login(people["foram"])

    text = client.get("/tasks/dashboard/?priority=high").content.decode()

    assert 'name="company"' in text and 'name="person"' in text and 'name="category"' in text
    assert '<option value="high" selected>High</option>' in text
    assert 'title="Remove all filters">Clear</a>' in text
