"""Tasks app (Phase T1): who sees what, the task rules, files, comments and alerts."""
from datetime import date, timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.tasks import services
from apps.tasks.models import Task, TaskComment
from core.accounts.models import CompanyRole, Role
from core.files.models import FileAttachment
from core.masters.models import Company, Employee
from core.notifications.models import Notification

User = get_user_model()
Status = Task.Status
HTMX = {"HTTP_HX_REQUEST": "true"}
DUE = date(2026, 11, 20)


@pytest.fixture(autouse=True)
def private_folder(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path


@pytest.fixture
def acme():
    return Company.objects.create(name="Acme", code="ACME")


@pytest.fixture
def globex():
    return Company.objects.create(name="Globex", code="GLOBEX")


def make_user(name, companies, admin=False):
    """A member sees only tasks they are part of; an admin sees every task of the company."""
    user = User.objects.create_user(email=f"{name}@example.com", password="a-long-password-123", first_name=name)
    role = Role.objects.create(name=f"role-{name}", allowed_apps=["tasks"], own_records_only=not admin)
    for company in companies:
        CompanyRole.objects.create(user=user, company=company, role=role)
    return user


def employee(company, user, code, reports_to=None):
    return Employee.objects.create(
        company=company, user=user, employee_code=code, first_name=user.first_name, reports_to=reports_to
    )


@pytest.fixture
def people(acme):
    """Saurabh creates tasks, Het owns them. Foram is Het's manager. Boss is the admin."""
    names = ("saurabh", "het", "amar", "foram", "ghosh", "outsider")
    team = {name: make_user(name, [acme]) for name in names}
    team["boss"] = make_user("boss", [acme], admin=True)
    foram = employee(acme, team["foram"], "E1")
    employee(acme, team["het"], "E2", reports_to=foram)
    return team


def make_task(people, acme, **extra):
    fields = {"title": "GSTR1", "owner": people["het"], "due_date": DUE, **extra}
    return services.create_task(people["saurabh"], acme, **fields)


def sees(user, task):
    return services.visible_tasks(user).filter(pk=task.pk).exists()


def pdf_file():
    return SimpleUploadedFile("proof.pdf", b"%PDF-1.4 test file", content_type="application/pdf")


# --- Who sees what ---------------------------------------------------------------------


@pytest.mark.django_db
def test_people_on_a_task_see_it_and_others_do_not(people, acme):
    task = make_task(people, acme, reviewer=people["amar"], collaborators=[people["ghosh"]])

    # creator, owner, reviewer, collaborator, manager, admin
    for name in ("saurabh", "het", "amar", "ghosh", "foram", "boss"):
        assert sees(people[name], task), name
    assert not sees(people["outsider"], task)


@pytest.mark.django_db
def test_person_with_an_action_sees_the_task(people, acme):
    task = make_task(people, acme)
    assert not sees(people["ghosh"], task)

    services.add_action(people["het"], task, "Send data", people["ghosh"], DUE)

    assert sees(people["ghosh"], task)


@pytest.mark.django_db
def test_manager_sees_tasks_of_all_levels_below(people, acme):
    top = make_user("top", [acme])
    top_employee = employee(acme, top, "E0")
    Employee.objects.filter(user=people["foram"]).update(reports_to=top_employee)
    task = make_task(people, acme)  # owner Het -> Foram -> Top

    assert sees(top, task)


@pytest.mark.django_db
def test_other_company_user_cannot_see_or_open_a_task(people, acme, globex, client):
    task = make_task(people, acme)
    gita = make_user("gita", [globex], admin=True)

    assert not sees(gita, task)
    client.force_login(gita)
    assert client.get(f"/tasks/{task.pk}/").status_code == 404


@pytest.mark.django_db
def test_outsider_gets_404_and_user_without_the_app_gets_403(people, acme, client):
    task = make_task(people, acme)
    client.force_login(people["outsider"])
    assert client.get(f"/tasks/{task.pk}/").status_code == 404

    no_app = User.objects.create_user(email="noapp@example.com", password="a-long-password-123", first_name="No")
    client.force_login(no_app)
    assert client.get("/tasks/list/mine/").status_code == 403


@pytest.mark.django_db
def test_lists_show_the_right_tasks(people, acme, client):
    task = make_task(people, acme)
    client.force_login(people["het"])
    assert task.title in client.get("/tasks/list/mine/").content.decode()
    assert task.title not in client.get("/tasks/list/assigned/").content.decode()

    client.force_login(people["saurabh"])
    assert task.title in client.get("/tasks/list/assigned/").content.decode()
    assert task.title in client.get("/tasks/list/all/").content.decode()


# --- Creating --------------------------------------------------------------------------


@pytest.mark.django_db
def test_task_numbers_run_per_company(people, acme, globex):
    first, second = make_task(people, acme), make_task(people, acme)
    gita = make_user("gita", [globex], admin=True)
    other = services.create_task(gita, globex, title="X", owner=gita, due_date=DUE)

    assert (first.code, second.code, other.code) == ("TSK-0001", "TSK-0002", "TSK-0001")


@pytest.mark.django_db
def test_people_of_another_company_cannot_be_put_on_a_task(people, acme, globex):
    gita = make_user("gita", [globex])

    with pytest.raises(ValidationError, match="work in Acme"):
        make_task(people, acme, owner=gita)
    with pytest.raises(ValidationError, match="work in Acme"):
        make_task(people, acme, collaborators=[gita])


@pytest.mark.django_db
def test_new_task_form_creates_a_task(people, acme, client):
    client.force_login(people["saurabh"])
    category = services.categories_of(acme).get(name="MIS")
    form_data = {
        "company": acme.pk, "title": "Bank reco", "owner": people["het"].pk, "due_date": "2026-11-25",
        "category": category.pk, "priority": "high", "collaborators": [people["amar"].pk], "comment": "Start early",
    }

    response = client.post("/tasks/new/", form_data, **HTMX)

    assert response.status_code == 200
    task = Task.objects.get(title="Bank reco")
    assert task.created_by == people["saurabh"] and task.priority == "high"
    assert list(task.collaborators.all()) == [people["amar"]]
    assert task.comments.get().text == "Start early"


# --- Rules -----------------------------------------------------------------------------


@pytest.mark.django_db
def test_moving_the_due_date_needs_a_comment_and_counts(people, acme):
    task = make_task(people, acme)
    later = DUE + timedelta(days=5)

    with pytest.raises(ValidationError, match="Write a comment"):
        services.update_task(people["het"], task, {"due_date": later})

    services.update_task(people["het"], task, {"due_date": later}, comment="Data came late")
    services.update_task(people["het"], task, {"due_date": later + timedelta(days=1)}, comment="Again")
    task.refresh_from_db()

    assert task.due_date_changes == 2
    assert task.comments.filter(is_system=True, text__startswith="Due date moved 20 Nov 2026 → 25 Nov 2026").exists()
    assert task.comments.filter(is_system=False, text="Data came late").exists()


@pytest.mark.django_db
def test_blocking_needs_a_comment(people, acme):
    task = make_task(people, acme)

    with pytest.raises(ValidationError, match="Write a comment"):
        services.update_task(people["het"], task, {"status": Status.BLOCKED})
    services.update_task(people["het"], task, {"status": Status.BLOCKED}, comment="Waiting for the bank")

    assert Task.objects.get(pk=task.pk).status == Status.BLOCKED


@pytest.mark.django_db
def test_collaborator_and_reviewer_cannot_change_the_task(people, acme, client):
    task = make_task(people, acme, reviewer=people["amar"], collaborators=[people["ghosh"]])

    for name in ("ghosh", "amar"):
        with pytest.raises(PermissionDenied):
            services.update_task(people[name], task, {"title": "Hacked"})
    for name in ("het", "saurabh", "foram", "boss"):  # owner, creator, manager, admin
        services.update_task(people[name], task, {"title": f"By {name}"})

    client.force_login(people["ghosh"])
    page = client.get(f"/tasks/{task.pk}/").content.decode()
    assert "You can view this task" in page and "Save changes" not in page


@pytest.mark.django_db
def test_saving_the_task_form_changes_the_task(people, acme, client):
    task = make_task(people, acme)
    client.force_login(people["het"])
    form_data = {
        "title": "GSTR1 final", "owner": people["het"].pk, "due_date": "2026-11-25", "priority": "low",
        "status": "in_progress", "collaborators": [people["amar"].pk], "comment": "",
    }

    refused = client.post(f"/tasks/{task.pk}/", form_data, **HTMX).content.decode()
    assert "Write a comment saying why" in refused
    assert Task.objects.get(pk=task.pk).title == "GSTR1"

    client.post(f"/tasks/{task.pk}/", {**form_data, "comment": "Client asked"}, **HTMX)
    task.refresh_from_db()
    assert (task.title, task.status, task.due_date_changes) == ("GSTR1 final", "in_progress", 1)
    assert list(task.collaborators.all()) == [people["amar"]]


@pytest.mark.django_db
def test_done_without_reviewer_completes_the_task(people, acme):
    task = make_task(people, acme)

    services.mark_done(people["het"], task)
    task.refresh_from_db()

    assert task.status == Status.COMPLETED and task.completed_at is not None
    with pytest.raises(ValidationError, match="already completed"):
        services.mark_done(people["het"], task)


@pytest.mark.django_db
def test_done_with_reviewer_goes_to_review_then_reviewer_decides(people, acme):
    task = make_task(people, acme, reviewer=people["amar"])

    services.mark_done(people["het"], task)
    assert task.status == Status.UNDER_REVIEW
    with pytest.raises(PermissionDenied):
        services.review_task(people["het"], task, approve=True)  # the owner cannot review their own work
    with pytest.raises(ValidationError, match="what must be fixed"):
        services.review_task(people["amar"], task, approve=False)

    services.review_task(people["amar"], task, approve=False, comment="Totals do not match")
    assert task.status == Status.IN_PROGRESS

    services.mark_done(people["het"], task)
    services.review_task(people["amar"], task, approve=True)
    assert task.status == Status.COMPLETED and task.completed_at is not None


@pytest.mark.django_db
def test_done_button_on_the_list_reloads_the_page(people, acme, client):
    task = make_task(people, acme)
    client.force_login(people["het"])
    assert f"/tasks/{task.pk}/done/" in client.get("/tasks/list/mine/").content.decode()

    response = client.post(f"/tasks/{task.pk}/done/", {"from": "list"}, **HTMX)

    assert response.status_code == 204 and response["HX-Refresh"] == "true"
    assert Task.objects.get(pk=task.pk).status == Status.COMPLETED


@pytest.mark.django_db
def test_only_creator_or_admin_cancels_and_cancelled_task_is_hidden_not_deleted(people, acme, client):
    task = make_task(people, acme)

    with pytest.raises(PermissionDenied):
        services.cancel_task(people["het"], task)  # the owner did not create it
    services.cancel_task(people["saurabh"], task)

    assert Task.objects.filter(pk=task.pk, is_active=False).exists()
    assert not sees(people["het"], task)
    client.force_login(people["het"])
    assert client.get(f"/tasks/{task.pk}/").status_code == 404


# --- Actions, comments, links, files ---------------------------------------------------


@pytest.mark.django_db
def test_actions_are_ticked_by_their_person_and_counted(people, acme):
    task = make_task(people, acme)
    action = services.add_action(people["het"], task, "Send data", people["ghosh"], DUE)
    services.add_action(people["het"], task, "File return", people["het"], DUE)

    with pytest.raises(PermissionDenied):
        services.toggle_action(people["amar"], action)
    with pytest.raises(PermissionDenied):
        services.add_action(people["ghosh"], task, "Sneaky", people["ghosh"], DUE)
    services.toggle_action(people["ghosh"], action)

    row = services.visible_tasks(people["het"]).get(pk=task.pk)
    assert (row.actions_done, row.actions_total, services.open_actions(task)) == (1, 2, 1)


@pytest.mark.django_db
def test_collaborator_can_comment_add_a_link_and_upload_but_outsider_cannot(people, acme, client):
    task = make_task(people, acme, collaborators=[people["ghosh"]])
    link = {"label": "Sheet", "url": "https://example.com/x"}

    client.force_login(people["ghosh"])
    assert client.post(f"/tasks/{task.pk}/comments/", {"text": "Data sent"}, **HTMX).status_code == 200
    assert client.post(f"/tasks/{task.pk}/links/", link, **HTMX).status_code == 200
    assert client.post(f"/files/tasks/task/{task.pk}/", {"file": pdf_file()}, **HTMX).status_code == 200
    assert task.comments.filter(text="Data sent").exists() and task.links.count() == 1
    assert FileAttachment.objects.filter(object_id=task.pk, original_name="proof.pdf").count() == 1
    page = client.get(f"/tasks/{task.pk}/").content.decode()
    assert "proof.pdf" in page and "Sheet" in page

    client.force_login(people["outsider"])
    assert client.post(f"/tasks/{task.pk}/comments/", {"text": "Hi"}, **HTMX).status_code == 404
    assert client.post(f"/files/tasks/task/{task.pk}/", {"file": pdf_file()}, **HTMX).status_code == 404
    assert FileAttachment.objects.count() == 1


@pytest.mark.django_db
def test_bad_link_gives_a_clear_error(people, acme):
    task = make_task(people, acme)

    with pytest.raises(ValidationError):
        services.add_link(people["het"], task, "Bad", "not a link")


# --- Alerts ----------------------------------------------------------------------------


def bell_titles(user):
    return list(Notification.objects.filter(user=user).values_list("title", flat=True))


@pytest.mark.django_db
def test_new_task_tells_owner_reviewer_and_collaborators_by_bell_and_email(people, acme):
    make_task(people, acme, reviewer=people["amar"], collaborators=[people["ghosh"]])

    assert bell_titles(people["het"]) == ["New task for you: GSTR1"]
    assert bell_titles(people["amar"]) == ["You are the reviewer: GSTR1"]
    assert bell_titles(people["ghosh"]) == ["You were added to a task: GSTR1"]
    assert bell_titles(people["saurabh"]) == []  # never the person who did it
    emailed = sorted(message.to[0] for message in mail.outbox)
    assert emailed == ["amar@example.com", "ghosh@example.com", "het@example.com"]


@pytest.mark.django_db
def test_comment_is_bell_only_and_review_request_is_emailed(people, acme):
    task = make_task(people, acme, reviewer=people["amar"])
    mail.outbox.clear()

    services.add_comment(people["het"], task, "Working on it")
    assert "New comment: GSTR1" in bell_titles(people["saurabh"])
    assert "New comment: GSTR1" in bell_titles(people["amar"])
    assert mail.outbox == []

    services.mark_done(people["het"], task)
    assert "Please review: GSTR1" in bell_titles(people["amar"])
    assert [message.to[0] for message in mail.outbox] == ["amar@example.com"]


@pytest.mark.django_db
def test_due_groups(people, acme):
    today = timezone.localdate()
    late = make_task(people, acme, due_date=today - timedelta(days=1))
    soon = make_task(people, acme, due_date=today + timedelta(days=3))
    done = make_task(people, acme, due_date=today - timedelta(days=1))
    services.mark_done(people["het"], done)

    groups = dict(services.visible_tasks(people["het"]).values_list("pk", "due_group"))

    assert groups == {late.pk: "overdue", soon.pk: "week", done.pk: "done"}
    assert TaskComment.objects.filter(task=done, is_system=True).exists()


# --- Found in the T1 review ------------------------------------------------------------


@pytest.mark.django_db
def test_owner_cannot_skip_the_reviewer_through_the_status_field(people, acme):
    task = make_task(people, acme, reviewer=people["amar"])

    with pytest.raises(ValidationError, match="must review this task"):
        services.update_task(people["het"], task, {"status": Status.COMPLETED})
    task.refresh_from_db()
    assert task.status == Status.NOT_STARTED

    services.update_task(people["boss"], task, {"status": Status.COMPLETED})  # an admin may
    assert Task.objects.get(pk=task.pk).status == Status.COMPLETED


@pytest.mark.django_db
def test_new_reviewer_is_told_when_set_later(people, acme):
    task = make_task(people, acme)

    services.update_task(people["het"], task, {"reviewer": people["amar"]})

    assert bell_titles(people["amar"]) == ["You are the reviewer: GSTR1"]


@pytest.mark.django_db
def test_only_people_who_can_open_tasks_can_get_a_task(people, acme):
    ravi = User.objects.create_user(email="ravi@example.com", password="a-long-password-123", first_name="Ravi")
    masters_only = Role.objects.create(name="masters-only", allowed_apps=["masters"])
    CompanyRole.objects.create(user=ravi, company=acme, role=masters_only)

    assert ravi not in services.people_of(acme)
    with pytest.raises(ValidationError, match="can open Tasks"):
        make_task(people, acme, owner=ravi)


@pytest.mark.django_db
def test_giving_the_task_away_sends_the_manager_back_to_the_list(people, acme, client):
    task = make_task(people, acme)  # owner Het reports to Foram; Amar does not
    client.force_login(people["foram"])
    form_data = {
        "title": task.title, "owner": people["amar"].pk, "due_date": "2026-11-20", "priority": "medium",
        "status": "not_started", "comment": "",
    }

    response = client.post(f"/tasks/{task.pk}/", form_data, **HTMX)

    assert Task.objects.get(pk=task.pk).owner == people["amar"]
    assert response.status_code == 204 and response["HX-Redirect"] == "/tasks/list/mine/"


@pytest.mark.django_db
def test_inactive_employee_record_gives_no_manager_access(people, acme):
    task = make_task(people, acme)
    assert sees(people["foram"], task)

    Employee.objects.filter(user=people["foram"]).update(is_active=False)
    foram = User.objects.get(pk=people["foram"].pk)  # a fresh login, as on the next page load

    assert not sees(foram, task)
