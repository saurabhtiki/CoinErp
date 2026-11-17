"""Tasks app (Phase T5, Part B): open actions on the dashboard, in the People table and in the Actions list."""
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.tasks import services
from apps.tasks.models import Task, TaskAction
from tests.test_tasks import HTMX, acme, globex, make_user, people, private_folder  # noqa: F401  shared fixtures

Status = Task.Status


def day(offset):
    return timezone.localdate() + timedelta(days=offset)


def task_for(people, acme, owner="het", due=10, **extra):
    return services.create_task(people["saurabh"], acme, title="GSTR1", owner=people[owner], due_date=day(due), **extra)


def action(people, task, owner, due, by="saurabh"):
    return services.add_action(people[by], task, "Send data", people[owner], day(due))


@pytest.fixture
def actions(people, acme):
    gstr = task_for(people, acme, priority="high")
    tds = task_for(people, acme)
    finished = task_for(people, acme)
    hidden = services.create_task(people["boss"], acme, title="Payroll", owner=people["boss"], due_date=day(10))
    made = {
        "amar_late": action(people, gstr, "amar", -2),
        "amar_today": action(people, gstr, "amar", 0),
        "het_week": action(people, tds, "het", 3),
        "het_later": action(people, tds, "het", 9),
        "ticked": action(people, tds, "amar", -1),
        "on_finished_task": action(people, finished, "amar", -1),
        "on_hidden_task": action(people, hidden, "boss", -1, by="boss"),
    }
    TaskAction.objects.filter(pk=made["ticked"].pk).update(is_done=True)
    Task.objects.filter(pk=finished.pk).update(status=Status.COMPLETED, completed_at=timezone.now())
    return made


def ids(rows):
    return {row.pk for row in rows}


@pytest.mark.django_db
def test_only_open_actions_on_open_tasks_the_user_may_see_count(people, acme, actions):
    numbers = services.dashboard_numbers(people["saurabh"])  # creator: sees his three tasks, not Payroll

    assert numbers["action_cards"] == {"overdue": 1, "today": 1, "week": 1, "mine": 0}
    assert ids(services.visible_open_actions(people["saurabh"])) == {
        actions[name].pk for name in ("amar_late", "amar_today", "het_week", "het_later")
    }
    assert services.dashboard_numbers(people["amar"])["action_cards"]["mine"] == 2


@pytest.mark.django_db
def test_filters_narrow_the_action_cards_and_person_means_the_actions_person(people, acme, actions):
    def cards(**filters):
        return services.dashboard_numbers(people["saurabh"], filters=filters)["action_cards"]

    assert cards(priority="high") == {"overdue": 1, "today": 1, "week": 0, "mine": 0}
    assert cards(person=str(people["het"].pk)) == {"overdue": 0, "today": 0, "week": 1, "mine": 0}
    assert cards(person=str(people["amar"].pk))["overdue"] == 1  # Amar owns no task, only actions


@pytest.mark.django_db
def test_people_table_counts_actions_by_the_actions_person(people, acme, actions):
    rows = {row.pk: row for row in services.people_numbers(people["foram"])}  # Het's manager

    amar, het = rows[people["amar"].pk], rows[people["het"].pk]
    assert (amar.open_actions_count, amar.overdue_actions_count, amar.open_count) == (2, 1, 0)
    assert (het.open_actions_count, het.overdue_actions_count) == (2, 0)
    assert people["boss"].pk not in rows  # Payroll is not Foram's team


@pytest.mark.django_db
def test_every_action_number_opens_exactly_the_actions_it_counted(client, people, acme, actions):
    client.force_login(people["foram"])
    context = client.get(f"/tasks/dashboard/?company={acme.pk}").context

    for card in context["action_cards"]:
        assert len(client.get(card["url"]).context["table"].page) == card["count"], card["label"]
    links = context["person_urls"]
    amar = people["amar"]
    assert ids(client.get(f"{links['open_actions']}&person={amar.pk}").context["table"].page) == {
        actions["amar_late"].pk, actions["amar_today"].pk
    }
    assert ids(client.get(f"{links['overdue_actions']}&person={amar.pk}").context["table"].page) == {
        actions["amar_late"].pk
    }


@pytest.mark.django_db
def test_actions_list_shortcut_search_and_row_opens_the_task_on_actions(client, people, acme, actions):
    client.force_login(people["saurabh"])

    page = client.get("/tasks/actions/?due_group=overdue")
    assert ids(page.context["table"].page) == {actions["amar_late"].pk}
    text = page.content.decode()
    assert f'/tasks/{actions["amar_late"].task_id}/?tab=actions' in text and ">Actions</a>" in text

    panel = client.get(f'/tasks/{actions["amar_late"].task_id}/?tab=actions', **HTMX).content.decode()
    assert "tab: 'actions'" in panel


@pytest.mark.django_db
def test_outsider_sees_no_actions_and_cannot_filter_by_a_stranger(client, people, acme, actions):
    client.force_login(people["outsider"])

    page = client.get(f"/tasks/actions/?person={people['amar'].pk}")

    assert not page.context["table"].page.object_list
    assert "The Person filter was ignored" in page.content.decode()
    assert services.dashboard_numbers(people["outsider"])["action_cards"] == {
        "overdue": 0, "today": 0, "week": 0, "mine": 0
    }


@pytest.mark.django_db
def test_my_open_actions_card_works_even_for_someone_with_no_tasks(client, people, acme):
    lonely = make_user("lonely", [acme])
    client.force_login(lonely)

    card = client.get("/tasks/dashboard/").context["action_cards"][3]
    page = client.get(card["url"])

    assert card["label"] == "My open actions" and card["count"] == 0
    assert "ignored" not in page.content.decode()  # the user is always a person they may pick


@pytest.mark.django_db
def test_people_links_show_only_what_the_people_table_counted(client, people, acme, actions):
    """Foram also sees a task outside her team (as a collaborator): it is in her lists, not in her People numbers."""
    foram, amar = people["foram"], people["amar"]
    side = services.create_task(people["boss"], acme, title="Audit", owner=amar, due_date=day(-1),
                                collaborators=[foram])
    services.add_action(people["boss"], side, "Count stock", amar, day(-3))
    client.force_login(foram)
    context = client.get("/tasks/dashboard/").context
    row = next(row for row in context["table"].page if row.pk == amar.pk)
    links = context["person_urls"]

    def shown(url):
        return len(client.get(f"{url}&person={amar.pk}").context["table"].page)

    assert (row.open_actions_count, row.overdue_actions_count, row.open_count, row.overdue_count) == (2, 1, 0, 0)
    assert shown(links["open_actions"]) == 2 and shown(links["overdue_actions"]) == 1
    assert shown(links["open"]) == 0 and shown(links["overdue"]) == 0
    assert len(client.get(f"/tasks/actions/?person={amar.pk}").context["table"].page) == 3  # without team=1


@pytest.mark.django_db
def test_task_list_reads_the_same_category_filter_as_the_actions_list(client, people, acme):
    mis = services.categories_of(acme).get(name="MIS")
    in_mis = task_for(people, acme, category=mis)
    task_for(people, acme)
    client.force_login(people["het"])

    page = client.get("/tasks/list/all/?category=MIS")

    assert {row.pk for row in page.context["table"].page} == {in_mis.pk}
    assert "Only: <strong>MIS</strong>" in page.content.decode() and ">Later</td>" in page.content.decode()  # When label from DUE_GROUPS


@pytest.mark.django_db
def test_task_and_action_cards_sit_in_two_tabs_and_the_picked_tab_is_remembered(client, people, acme, actions):
    client.force_login(people["foram"])

    first = client.get("/tasks/dashboard/").content.decode()
    picked = client.get("/tasks/dashboard/?priority=high&cards=actions").content.decode()

    def checked(page, tab):
        tag = page[page.index(f'id="card-tab-{tab}"'):]
        return " checked" in tag[:tag.index(">")]

    assert checked(first, "tasks") and not checked(first, "actions")  # Tasks tab first
    assert checked(picked, "actions") and not checked(picked, "tasks")  # a filter change keeps Actions
    assert 'form="dashboard-filters"' in first  # the tabs travel with the filters
