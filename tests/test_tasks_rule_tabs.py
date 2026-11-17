"""Tasks app (Phase T4, Part B): the repeating task form with tabs, and what each new task gets from its rule."""
from datetime import date

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import QueryDict

from apps.tasks import services
from apps.tasks.forms import NewTaskParts
from apps.tasks.models import RecurringTask, Task
from core.files.models import FileAttachment
from core.files.services import attach, attachments_for, can_remove, file_for_download, remove
from core.notifications.models import Notification
from tests.test_tasks import (  # noqa: F401  shared fixtures
    DUE,
    HTMX,
    acme,
    globex,
    make_user,
    pdf_file,
    people,
    private_folder,
)

OCT_RUN = date(2026, 11, 4)  # the job makes "GSTR1 - Oct 2026", due Wed 11 Nov
NOV_RUN = date(2026, 12, 4)  # ... and "GSTR1 - Nov 2026", due Fri 11 Dec


def rule_data(people, acme, **extra):
    data = {
        "company": acme.pk, "title": "GSTR1", "owner": people["het"].pk, "priority": "medium",
        "frequency": "monthly", "repeat_every": 1, "due_day": 11, "due_in_next_period": "on",
        "off_day_rule": "previous", "create_days_before": 7, "start_date": "2026-10-01",
        "collaborators": [people["ghosh"].pk],
    }
    data.update(extra)
    return data


def make_rule(people, acme, **extra):
    fields = {
        "title": "GSTR1", "owner": people["het"], "collaborators": [people["ghosh"]], "frequency": "monthly",
        "due_day": 11, "due_in_next_period": True, "start_date": date(2026, 10, 1), **extra,
    }
    return services.save_rule(people["saurabh"], acme, **fields)


def file_text(attachment):
    with attachment.file.open("rb") as handle:
        return handle.read()


@pytest.mark.django_db
def test_new_rule_form_saves_everything_and_each_task_gets_actions_links_and_its_own_file(people, acme, client):
    client.force_login(people["saurabh"])
    data = rule_data(
        people, acme,
        action_title=["Send data to CA"], action_owner=[people["amar"].pk], action_days_before_due=["3"],
        link_label=["GST sheet"], link_url=["https://example.com/sheet"],
        comment="Should we move this to day 10?", files=[pdf_file()],
    )

    response = client.post("/tasks/repeating/new/", data, **HTMX)

    assert response.status_code == 200
    rule = RecurringTask.objects.get()
    assert [(action.title, action.days_before_due) for action in rule.actions.all()] == [("Send data to CA", 3)]
    assert rule.links.get().label == "GST sheet"
    assert rule.comments.get().text == "Should we move this to day 10?"
    rule_file = attachments_for(rule).get()

    assert services.create_due_tasks(today=OCT_RUN) == 1
    task = Task.objects.get()
    assert [(action.title, action.due_date) for action in task.actions.all()] == [("Send data to CA", date(2026, 11, 8))]
    assert [(link.label, link.url) for link in task.links.all()] == [("GST sheet", "https://example.com/sheet")]
    task_file = attachments_for(task).get()
    assert task_file.original_name == "proof.pdf" and task_file.file.name != rule_file.file.name  # its own copy
    assert file_text(task_file) == file_text(rule_file)
    assert not task.comments.filter(is_system=False).exists()  # rule comments stay on the rule


@pytest.mark.django_db
def test_bad_rows_on_the_new_rule_form_save_nothing_and_mark_their_tabs(people, acme, client):
    client.force_login(people["saurabh"])
    data = rule_data(
        people, acme, action_title=["Send data"], action_owner=[people["amar"].pk], action_days_before_due=["-2"],
        link_label=["Sheet"], link_url=["not a link"], files=[SimpleUploadedFile("tool.exe", b"MZ program")],
    )

    page = client.post("/tasks/repeating/new/", data, **HTMX).content.decode()

    assert not RecurringTask.objects.exists() and not FileAttachment.objects.exists()
    assert "Action 1: days before the due date must be a whole number from 0 to 365." in page
    assert "Link 1:" in page and "tool.exe: This type of file is not allowed" in page
    assert "tab: 'actions'" in page and "Please choose them again" in page


@pytest.mark.django_db
def test_a_details_error_keeps_the_rows_and_opens_details(people, acme, client):
    client.force_login(people["saurabh"])
    data = rule_data(people, acme, title="", action_title=["Send data"], action_owner=[people["amar"].pk],
                     action_days_before_due=["2"])

    page = client.post("/tasks/repeating/new/", data, **HTMX).content.decode()

    assert not RecurringTask.objects.exists()
    assert "tab: 'details'" in page and '"title": "Send data"' in page  # the typed row comes back


@pytest.mark.django_db
def test_rule_changes_reach_only_later_tasks(people, acme):
    rule = make_rule(people, acme, links=[{"label": "Old sheet", "url": "https://example.com/old"}],
                     files=[pdf_file()])
    services.create_due_tasks(today=OCT_RUN)
    october = Task.objects.get()

    services.remove_rule_link(people["saurabh"], rule.links.get())
    services.add_rule_link(people["saurabh"], rule, "New sheet", "https://example.com/new")
    remove(attachments_for(rule).get(), people["saurabh"])
    services.create_due_tasks(today=NOV_RUN)
    november = Task.objects.exclude(pk=october.pk).get()

    assert list(october.links.values_list("label", flat=True)) == ["Old sheet"]
    assert list(november.links.values_list("label", flat=True)) == ["New sheet"]
    october_file = attachments_for(october).get()
    assert file_for_download(people["het"], october_file.file.name) is not None  # kept after the rule's file went
    assert not attachments_for(november).exists()


@pytest.mark.django_db
def test_collaborator_cannot_change_rule_files_or_links_but_can_download_and_comment(people, acme, client):
    rule = make_rule(people, acme, files=[pdf_file()])
    rule_file = attachments_for(rule).get()
    ghosh = people["ghosh"]

    with pytest.raises(PermissionDenied):
        services.add_rule_link(ghosh, rule, "Sheet", "https://example.com")
    with pytest.raises(ValidationError, match="Only the owner, the creator or their manager"):
        attach(rule, pdf_file(), ghosh)
    assert not can_remove(rule_file, ghosh)
    assert can_remove(rule_file, people["foram"])  # the owner's manager may, though someone else uploaded it
    assert file_for_download(ghosh, rule_file.file.name) is not None

    client.force_login(ghosh)
    client.post(f"/files/tasks/recurringtask/{rule.pk}/", {"file": pdf_file()}, **HTMX)
    page = client.post(f"/tasks/repeating/{rule.pk}/comments/", {"text": "Day 10 is better"}, **HTMX).content.decode()

    assert attachments_for(rule).count() == 1
    assert "Day 10 is better" in page and "Add link" not in page
    bell = Notification.objects.get(user=people["het"], title="New comment on repeating task: GSTR1")
    assert bell.link == f"/tasks/repeating/{rule.pk}/"


@pytest.mark.django_db
def test_outsider_cannot_see_comment_on_or_download_anything_of_the_rule(people, acme, client):
    rule = make_rule(people, acme, files=[pdf_file()])
    outsider = people["outsider"]

    with pytest.raises(PermissionDenied):
        services.add_rule_comment(outsider, rule, "Hello")
    assert file_for_download(outsider, attachments_for(rule).get().file.name) is None

    client.force_login(outsider)
    assert client.get(f"/tasks/repeating/{rule.pk}/", **HTMX).status_code == 404
    assert client.post(f"/tasks/repeating/{rule.pk}/comments/", {"text": "Hi"}, **HTMX).status_code == 404
    assert client.post(f"/files/tasks/recurringtask/{rule.pk}/", {"file": pdf_file()}, **HTMX).status_code == 404
    assert not rule.comments.exists() and attachments_for(rule).count() == 1


@pytest.mark.django_db
def test_saved_rule_panel_shows_the_tabs_and_manager_adds_a_link(people, acme, client):
    rule = make_rule(people, acme)
    client.force_login(people["het"])

    page = client.post(f"/tasks/repeating/{rule.pk}/links/", {"label": "Sheet", "url": "https://example.com"},
                       **HTMX).content.decode()

    assert rule.links.get().label == "Sheet"
    assert "tab: 'files'" in page and "Files &amp; links (1)" in page and "Comments (0)" in page


@pytest.mark.django_db
def test_new_task_form_checks_actions_against_the_task_due_date_before_the_service(people, acme):
    data = QueryDict(mutable=True)
    data.setlist("action_title", ["Early", "Late"])
    data.setlist("action_owner", [str(people["amar"].pk)] * 2)
    data.setlist("action_due_date", ["2026-11-10", "2026-11-25"])
    parts = NewTaskParts(data, company=acme)

    assert not parts.is_valid(DUE)
    assert parts.errors["actions"] == ["Action 2: Action due date can't be after the task's due date (20 Nov 2026)."]


@pytest.mark.django_db
def test_task_panel_shows_the_upload_form_to_people_on_the_task(people, acme, client):
    task = services.create_task(people["saurabh"], acme, title="GSTR1", owner=people["het"], due_date=DUE,
                                collaborators=[people["ghosh"]])
    client.force_login(people["ghosh"])  # a collaborator may add files to a task (not to a rule)

    assert "Add a file" in client.get(f"/tasks/{task.pk}/", **HTMX).content.decode()
