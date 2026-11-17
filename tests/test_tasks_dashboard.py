"""Tasks app (Phase T3, Part A): the dashboard counts only what each person may see."""
from datetime import date, datetime, timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.tasks import services
from apps.tasks.models import Task
from core.access.services import team_rows
from core.accounts.models import CompanyRole
from tests.test_tasks import acme, globex, make_user, people, private_folder  # noqa: F401  shared fixtures

Status = Task.Status
User = get_user_model()
TODAY = date(2026, 11, 17)


def add(people, company, owner="het", due=TODAY, by="saurabh", status=None, **extra):
    fields = {"title": "GSTR1", "owner": people[owner] if isinstance(owner, str) else owner, "due_date": due, **extra}
    task = services.create_task(people[by] if isinstance(by, str) else by, company, **fields)
    if status:
        Task.objects.filter(pk=task.pk).update(status=status)
    return task


def finish(task, on):
    """Mark completed on a given day (mark_done always uses now)."""
    Task.objects.filter(pk=task.pk).update(
        status=Status.COMPLETED, completed_at=timezone.make_aware(datetime.combine(on, datetime.min.time()))
    )


def person_row(user, person, today=TODAY):
    return services.people_numbers(user, today).filter(pk=person.pk).first()


# --- Count cards ------------------------------------------------------------------------


@pytest.mark.django_db
def test_cards_count_open_tasks_by_due_date(people, acme):
    add(people, acme, due=TODAY - timedelta(days=2))  # overdue
    add(people, acme, due=TODAY)  # today
    add(people, acme, due=TODAY + timedelta(days=3))  # next 7 days
    add(people, acme, due=TODAY + timedelta(days=30))  # later: no card
    finish(add(people, acme, due=TODAY - timedelta(days=5)), TODAY)  # completed: not counted
    add(people, acme, due=TODAY + timedelta(days=30), status=Status.BLOCKED)

    cards = services.dashboard_numbers(people["het"], TODAY)["cards"]

    assert (cards["overdue"], cards["today"], cards["week"], cards["blocked"]) == (1, 1, 1, 1)


@pytest.mark.django_db
def test_review_card_counts_only_tasks_waiting_for_me(people, acme):
    task = add(people, acme, reviewer=people["amar"])
    Task.objects.filter(pk=task.pk).update(status=Status.UNDER_REVIEW)
    add(people, acme, reviewer=people["amar"])  # not sent for review yet

    assert services.dashboard_numbers(people["amar"], TODAY)["cards"]["review"] == 1
    assert services.dashboard_numbers(people["het"], TODAY)["cards"]["review"] == 0
    assert list(services.waiting_for_my_review(people["amar"])) == [task]


@pytest.mark.django_db
def test_cards_never_count_other_company_or_unseen_tasks(people, acme, globex):
    stranger = make_user("stranger", [globex], admin=True)
    add({"stranger": stranger}, globex, owner=stranger, by=stranger, due=TODAY)
    add(people, acme, owner="amar", by="amar", due=TODAY)  # Het is not part of it

    assert services.dashboard_numbers(people["het"], TODAY)["cards"]["today"] == 0
    assert services.dashboard_numbers(people["boss"], TODAY)["cards"]["today"] == 1  # admin of Acme only


@pytest.mark.django_db
def test_charts_group_open_tasks_by_status_and_category(people, acme):
    mis = services.categories_of(acme).get(name="MIS")
    add(people, acme, category=mis)
    add(people, acme, category=mis, status=Status.IN_PROGRESS)
    add(people, acme)

    numbers = services.dashboard_numbers(people["het"], TODAY)

    assert numbers["by_status"] == [("not_started", "Not Started", 2), ("in_progress", "In Progress", 1)]
    assert numbers["by_category"] == [("MIS", "MIS", 2), (services.NO_CATEGORY, "No category", 1)]


# --- People table -----------------------------------------------------------------------


@pytest.mark.django_db
def test_people_row_counts_and_on_time_percent(people, acme):
    add(people, acme, due=TODAY - timedelta(days=1))  # open, overdue
    add(people, acme, due=TODAY + timedelta(days=1))  # open
    finish(add(people, acme, due=TODAY), TODAY - timedelta(days=1))  # on time
    finish(add(people, acme, due=TODAY - timedelta(days=10)), TODAY - timedelta(days=2))  # late
    finish(add(people, acme, due=date(2026, 10, 1)), date(2026, 10, 1))  # last month: not counted

    row = person_row(people["het"], people["het"])

    assert (row.open_count, row.overdue_count, row.done_count, row.on_time_percent) == (2, 1, 2, 50)


@pytest.mark.django_db
def test_on_time_is_empty_when_nothing_completed_this_month(people, acme):
    add(people, acme)
    assert person_row(people["het"], people["het"]).on_time_percent is None


@pytest.mark.django_db
def test_member_sees_only_own_row(people, acme):
    add(people, acme, owner="het", by="saurabh")
    add(people, acme, owner="saurabh", by="saurabh", collaborators=[people["het"]])  # Het can see it, not his

    assert list(services.people_numbers(people["het"], TODAY)) == [people["het"]]


@pytest.mark.django_db
def test_manager_sees_team_rows_and_admin_sees_everyone(people, acme):
    add(people, acme, owner="het")
    add(people, acme, owner="amar", by="amar")

    assert set(services.people_numbers(people["foram"], TODAY)) == {people["het"]}  # Het reports to Foram
    assert set(services.people_numbers(people["boss"], TODAY)) == {people["het"], people["amar"]}
    assert not services.people_numbers(people["outsider"], TODAY).exists()


@pytest.mark.django_db
def test_team_rows_keeps_companies_apart(people, acme, globex):
    """Foram manages Het only in Acme: Het's Globex tasks are not hers to count."""
    CompanyRole.objects.create(user=people["het"], company=globex, role=people["het"].company_roles.first().role)
    in_acme = add(people, acme, owner="het")
    add(people, globex, owner="het", by="het")

    assert list(team_rows(Task.objects.all(), people["foram"])) == [in_acme]


# --- Page -------------------------------------------------------------------------------


@pytest.mark.django_db
def test_dashboard_page_shows_cards_links_and_people(client, people, acme):
    add(people, acme, due=timezone.localdate() - timedelta(days=1))
    client.force_login(people["het"])

    page = client.get("/tasks/dashboard/")

    assert page.status_code == 200
    text = page.content.decode()
    assert "/tasks/list/all/?due_group=overdue" in text
    assert "/tasks/list/review/" in text
    assert "vendor/chart.umd.min.js" in text
    assert page.context["cards"][0]["count"] == 1
    assert list(page.context["table"].page) == [people["het"]]


@pytest.mark.django_db
def test_overdue_card_link_opens_only_overdue_tasks(client, people, acme):
    late = add(people, acme, due=timezone.localdate() - timedelta(days=1))
    add(people, acme, due=timezone.localdate() + timedelta(days=1))
    client.force_login(people["het"])

    page = client.get("/tasks/list/all/?due_group=overdue")

    assert [row.pk for row in page.context["table"].page] == [late.pk]


@pytest.mark.django_db
def test_dashboard_needs_tasks_app(client, people):
    no_app = User.objects.create_user(email="noapp@example.com", password="a-long-password-123", first_name="No")
    client.force_login(no_app)
    assert client.get("/tasks/dashboard/").status_code == 403
