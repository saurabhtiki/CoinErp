"""Tasks app (Phase T4, Part A): the New task form saves actions, files, links and a comment in one go."""
from datetime import date

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.tasks import services
from apps.tasks.models import Task
from core.files.models import FileAttachment
from core.files.services import file_for_download
from core.notifications.models import Notification
from tests.test_tasks import (  # noqa: F401  shared fixtures
    DUE,
    HTMX,
    acme,
    globex,
    make_task,
    make_user,
    pdf_file,
    people,
    private_folder,
)


def new_task_data(people, acme, **extra):
    data = {"company": acme.pk, "title": "Bank reco", "owner": people["het"].pk, "due_date": "2026-11-20",
            "priority": "medium"}
    data.update(extra)
    return data


def bell_titles(user):
    return list(Notification.objects.filter(user=user).values_list("title", flat=True))


@pytest.mark.django_db
def test_new_task_form_saves_actions_links_files_and_comment_together(people, acme, client):
    client.force_login(people["saurabh"])
    data = new_task_data(
        people, acme,
        action_title=["Send data to CA", "File return"],
        action_owner=[people["amar"].pk, people["het"].pk],
        action_due_date=["2026-11-18", "2026-11-20"],
        link_label=["GST sheet"], link_url=["https://example.com/sheet"],
        comment="Use last year's file as a sample", files=[pdf_file()],
    )

    response = client.post("/tasks/new/", data, **HTMX)

    assert response.status_code == 200
    task = Task.objects.get(title="Bank reco")
    assert [(action.title, action.owner, action.due_date) for action in task.actions.all()] == [
        ("Send data to CA", people["amar"], date(2026, 11, 18)),
        ("File return", people["het"], date(2026, 11, 20)),
    ]
    assert task.links.get().label == "GST sheet"
    assert task.comments.get().text == "Use last year's file as a sample"
    assert FileAttachment.objects.get(object_id=task.pk).original_name == "proof.pdf"
    assert "New action for you: Send data to CA" in bell_titles(people["amar"])
    assert not any(title.startswith("New action") for title in bell_titles(people["het"]))  # owner: one alert only


@pytest.mark.django_db
def test_action_due_after_the_task_saves_nothing_and_marks_the_actions_tab(people, acme, client):
    client.force_login(people["saurabh"])
    data = new_task_data(
        people, acme, action_title=["Send data"], action_owner=[people["amar"].pk], action_due_date=["2026-11-25"],
        files=[pdf_file()],
    )

    page = client.post("/tasks/new/", data, **HTMX).content.decode()

    assert not Task.objects.exists() and not FileAttachment.objects.exists()
    assert "Action 1: Action due date can&#x27;t be after the task&#x27;s due date (20 Nov 2026)." in page
    assert "tab: 'actions'" in page  # the form opens on the tab with the error
    assert "Please choose them again" in page  # the browser drops chosen files on an error


@pytest.mark.django_db
def test_wrong_file_or_bad_link_saves_nothing(people, acme, client):
    client.force_login(people["saurabh"])
    program = SimpleUploadedFile("tool.exe", b"MZ program")

    page = client.post("/tasks/new/", new_task_data(people, acme, files=[program]), **HTMX).content.decode()
    assert not Task.objects.exists()
    assert "tool.exe: This type of file is not allowed" in page and "tab: 'files'" in page

    page = client.post(
        "/tasks/new/", new_task_data(people, acme, link_label=["Sheet"], link_url=["not a link"]), **HTMX
    ).content.decode()
    assert not Task.objects.exists() and "Link 1:" in page


@pytest.mark.django_db
def test_action_rows_need_a_person_and_a_date_and_blank_rows_are_skipped(people, acme, client):
    client.force_login(people["saurabh"])
    data = new_task_data(
        people, acme, action_title=["Send data", ""], action_owner=["", people["het"].pk], action_due_date=["", ""],
    )

    page = client.post("/tasks/new/", data, **HTMX).content.decode()

    assert not Task.objects.exists()
    assert "Action 1: pick who does it." in page and "Action 1: pick a due date." in page
    assert "Action 2" not in page  # the empty second row is ignored


@pytest.mark.django_db
def test_action_for_someone_of_another_company_is_refused(people, acme, globex):
    stranger = make_user("stranger", [globex])
    action = {"title": "Send data", "owner": stranger, "due_date": DUE}

    with pytest.raises(ValidationError) as refused:
        services.create_task(people["saurabh"], acme, title="GSTR1", owner=people["het"], due_date=DUE, actions=[action])

    assert "actions" in refused.value.message_dict and not Task.objects.exists()


@pytest.mark.django_db
def test_errors_on_several_tabs_show_together_and_details_opens_first(people, acme, client):
    client.force_login(people["saurabh"])
    data = new_task_data(people, acme, title="", link_label=["Sheet"], link_url=["not a link"])

    page = client.post("/tasks/new/", data, **HTMX).content.decode()

    assert not Task.objects.exists() and "tab: 'details'" in page
    assert "Link 1:" in page  # shown now, not only after the title is fixed


@pytest.mark.django_db
def test_side_panel_refuses_an_action_due_after_the_task(people, acme):
    task = make_task(people, acme)

    with pytest.raises(ValidationError, match="can't be after the task's due date"):
        services.add_action(people["het"], task, "Late step", people["amar"], date(2026, 11, 21))
    services.add_action(people["het"], task, "On time", people["amar"], DUE)
    assert task.actions.count() == 1


@pytest.mark.django_db
def test_files_added_on_the_new_form_open_only_for_people_who_see_the_task(people, acme):
    task = services.create_task(people["saurabh"], acme, title="GSTR1", owner=people["het"], due_date=DUE,
                                files=[pdf_file()])
    stored = FileAttachment.objects.get(object_id=task.pk).file.name

    assert file_for_download(people["het"], stored) is not None
    assert file_for_download(people["outsider"], stored) is None
