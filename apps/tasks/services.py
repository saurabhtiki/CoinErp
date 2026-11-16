"""Tasks business rules. Who may see or change a task is asked from core.access, never decided here.

Example:
    task = create_task(saurabh, acme, title="GSTR1", owner=het, due_date=date(2026, 11, 18))
    update_task(het, task, {"due_date": date(2026, 11, 25)}, comment="Data came late")  # counter +1
    mark_done(het, task)  # Completed, or Under Review if the task has a reviewer
"""
import logging
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Case, Count, Max, Q, Value, When
from django.urls import reverse
from django.utils import timezone

from core.access.services import (
    can_manage_record,
    can_see_record,
    is_person_or_admin,
    is_person_or_manager,
    manages_visible_record,
    users_for_app,
)
from core.masters.models import Company
from core.notifications.models import NotificationLog
from core.notifications.services import notify

from .models import Task, TaskAction, TaskCategory, TaskComment, TaskLink

logger = logging.getLogger(__name__)
User = get_user_model()
Status = Task.Status
BELL_ONLY = (NotificationLog.Channel.IN_APP,)
DEFAULT_CATEGORIES = ("MIS", "Compliance", "Receivables", "Stock Audit", "Other")
EDITABLE_FIELDS = ("title", "description", "owner", "reviewer", "category", "priority", "status", "due_date")

DUE_GROUPS = {
    "overdue": "Overdue",
    "today": "Due today",
    "week": "Next 7 days",
    "later": "Later",
    "done": "Completed",
}


# ---------- reading ----------


def visible_tasks(user):
    """Every task the user may see (cancelled ones left out), with what the lists show."""
    today = timezone.localdate()
    return (
        Task.objects.for_user(user)
        .filter(is_active=True)
        .annotate(
            due_group=Case(
                When(status=Status.COMPLETED, then=Value("done")),
                When(due_date__lt=today, then=Value("overdue")),
                When(due_date=today, then=Value("today")),
                When(due_date__lte=today + timedelta(days=7), then=Value("week")),
                default=Value("later"),
            ),
            actions_total=Count("actions", distinct=True),
            actions_done=Count("actions", filter=Q(actions__is_done=True), distinct=True),
        )
    )


def my_tasks(user):
    """Tasks I work on: owner, reviewer, collaborator, or I have an action in it."""
    return visible_tasks(user).filter(
        Q(owner=user)
        | Q(reviewer=user)
        | Q(pk__in=Task.collaborators.through.objects.filter(user=user).values("task_id"))
        | Q(pk__in=TaskAction.objects.filter(owner=user).values("task_id"))
    )


def assigned_by_me(user):
    """Tasks I gave to someone else."""
    return visible_tasks(user).filter(created_by=user).exclude(owner=user)


def people_of(company):
    """Active users who can open Tasks in this company: the people a task there can be given to."""
    return users_for_app(company, Task.access_app_code()).order_by("first_name")


def categories_of(company):
    """The company's categories. The usual five are made the first time they are needed."""
    if not TaskCategory.objects.filter(company=company).exists():
        TaskCategory.objects.bulk_create(TaskCategory(company=company, name=name) for name in DEFAULT_CATEGORIES)
    return TaskCategory.objects.filter(company=company, is_active=True)


# Who may do what is asked from core.access. Pass visible=True for a task already fetched through
# visible_tasks() (e.g. when drawing the panel): the answer is the same, without more queries.


def can_manage(user, task, visible=False):
    return manages_visible_record(user, task) if visible else can_manage_record(user, task)


def can_finish_row(user, task):
    """Done button on a list row (the row is already one the user may see)."""
    return task.status not in (Status.COMPLETED, Status.UNDER_REVIEW) and manages_visible_record(user, task)


def can_cancel(user, task, visible=False):
    """Only the creator or an admin of the company cancels a task."""
    return is_person_or_admin(user, task.created_by_id, task, visible)


def can_review(user, task, visible=False):
    """The reviewer (or an admin) decides on a task that is under review."""
    return task.status == Status.UNDER_REVIEW and is_person_or_admin(user, task.reviewer_id, task, visible)


def can_change_action(user, action, visible=False):
    """The person doing the action, or whoever may change the task, ticks it."""
    return is_person_or_manager(user, action.owner_id, action.task, visible)


def open_actions(task):
    return task.actions.filter(is_done=False).count()


# ---------- helpers ----------


def _require(allowed, message):
    if not allowed:
        logger.warning("Refused: %s", message)
        raise PermissionDenied(message)


def _refuse(errors):
    """Log a broken rule, then raise it for the screen to show."""
    logger.info("Task rule refused: %s", errors)
    raise ValidationError(errors)


def _check_people(company, **people):
    """Owner, reviewer and collaborators must be people of the task's company."""
    allowed = set(people_of(company).values_list("pk", flat=True))
    errors = {}
    for field, value in people.items():
        users = value if isinstance(value, (list, tuple, set)) else [value]
        if any(person is not None and person.pk not in allowed for person in users):
            errors[field] = f"Pick only people who work in {company} and can open Tasks."
    if errors:
        _refuse(errors)


def _system_note(task, user, text):
    TaskComment.objects.create(task=task, created_by=user, text=text, is_system=True)


def task_link(task):
    return reverse("tasks:detail", args=[task.pk])


def _people_on(task):
    people = {task.owner, *task.collaborators.all()}
    if task.reviewer:
        people.add(task.reviewer)
    if task.created_by:
        people.add(task.created_by)
    return people


def _tell(users, actor, task, title, message="", channels=None):
    """Notify each user once, never the person who did the action."""
    for user in {person for person in users if person and person.pk != actor.pk}:
        if channels:
            notify(user, title, message, channels=channels, link=task_link(task))
        else:
            notify(user, title, message, link=task_link(task))


def _day(value):
    return value.strftime("%d %b %Y")


# ---------- creating and changing ----------


@transaction.atomic
def create_task(user, company, *, title, owner, due_date, category=None, priority=Task.Priority.MEDIUM,
                reviewer=None, collaborators=(), description="", first_comment=""):
    collaborators = [person for person in collaborators if person.pk != owner.pk]
    _check_people(company, owner=owner, reviewer=reviewer, collaborators=collaborators)
    if category is not None and category.company_id != company.pk:
        _refuse({"category": f"Pick a category of {company}."})
    Company.objects.select_for_update().get(pk=company.pk)  # one new task at a time per company: no twin numbers
    last_number = Task.objects.filter(company=company).aggregate(last=Max("number"))["last"] or 0
    task = Task.objects.create(
        company=company, created_by=user, number=last_number + 1, title=title, description=description,
        owner=owner, reviewer=reviewer, category=category, priority=priority, due_date=due_date,
    )
    task.collaborators.set(collaborators)
    if first_comment.strip():
        TaskComment.objects.create(task=task, created_by=user, text=first_comment.strip())
    due = _day(due_date)
    _tell([owner], user, task, f"New task for you: {task.title}", f"{task.code}, due {due}.")
    _tell([reviewer], user, task, f"You are the reviewer: {task.title}", f"{task.code}, due {due}.")
    _tell(collaborators, user, task, f"You were added to a task: {task.title}", f"{task.code}, due {due}.")
    return task


@transaction.atomic
def update_task(user, task, changes, comment="", collaborators=None):
    """Change task fields. Example: update_task(het, task, {"status": "blocked"}, comment="Waiting for bank")."""
    _require(can_manage(user, task), "Only the owner, the creator, the owner's manager or an admin can change this task.")
    changes = {field: value for field, value in changes.items() if field in EDITABLE_FIELDS}
    comment = comment.strip()
    old_due, old_owner, old_reviewer, old_status = task.due_date, task.owner, task.reviewer, task.status
    new_due = changes.get("due_date", old_due)
    new_status = changes.get("status", old_status)
    date_moved = new_due != old_due
    now_blocked = new_status == Status.BLOCKED and old_status != Status.BLOCKED
    if (date_moved or now_blocked) and not comment:
        _refuse({"comment": "Write a comment saying why you changed the due date or blocked the task."})
    new_reviewer = changes.get("reviewer", task.reviewer)
    if new_status == Status.UNDER_REVIEW and not new_reviewer:
        _refuse({"status": "Pick a reviewer before sending the task for review."})
    completes = new_status == Status.COMPLETED and old_status != Status.COMPLETED
    if completes and new_reviewer and not is_person_or_admin(user, new_reviewer.pk, task):
        _refuse({"status": f"{new_reviewer.first_name} must review this task. Pick Under Review, or use Done."})
    _check_people(
        task.company, owner=changes.get("owner", task.owner), reviewer=changes.get("reviewer"),
        collaborators=collaborators or [],
    )
    for field, value in changes.items():
        setattr(task, field, value)
    if date_moved:
        task.due_date_changes += 1
        _system_note(task, user, f"Due date moved {_day(old_due)} → {_day(new_due)}.")
    if new_status != old_status:
        task.completed_at = timezone.now() if new_status == Status.COMPLETED else None
        _system_note(task, user, f"Status changed: {Status(old_status).label} → {Status(new_status).label}.")
    task.save()
    if collaborators is not None:
        added = [person for person in collaborators if person not in set(task.collaborators.all())]
        task.collaborators.set([person for person in collaborators if person.pk != task.owner_id])
        _tell(added, user, task, f"You were added to a task: {task.title}", task.code)
    if comment:
        TaskComment.objects.create(task=task, created_by=user, text=comment)
    due = f"{task.code}, due {_day(task.due_date)}."
    if task.owner != old_owner:
        _tell([task.owner], user, task, f"New task for you: {task.title}", due)
    if task.reviewer != old_reviewer:
        _tell([task.reviewer], user, task, f"You are the reviewer: {task.title}", due)
    if date_moved:
        _tell([task.created_by, task.reviewer], user, task, f"Due date moved: {task.title}",
              f"{_day(old_due)} → {_day(new_due)}. {comment}", channels=BELL_ONLY)
    if new_status == Status.UNDER_REVIEW and old_status != Status.UNDER_REVIEW:
        _tell([task.reviewer], user, task, f"Please review: {task.title}", f"{task.code} is waiting for your check.")
    return task


@transaction.atomic
def mark_done(user, task):
    """One-click Done. With a reviewer (other than me) the task first goes to Under Review."""
    _require(can_manage(user, task), "Only the owner, the creator, the owner's manager or an admin can finish this task.")
    if task.status in (Status.COMPLETED, Status.UNDER_REVIEW):
        _refuse(f"This task is already {task.get_status_display().lower()}.")
    needs_review = task.reviewer_id and task.reviewer_id != user.pk
    old_label = task.get_status_display()
    task.status = Status.UNDER_REVIEW if needs_review else Status.COMPLETED
    task.completed_at = None if needs_review else timezone.now()
    task.save()
    _system_note(task, user, f"Status changed: {old_label} → {task.get_status_display()}.")
    if needs_review:
        _tell([task.reviewer], user, task, f"Please review: {task.title}", f"{task.code} is waiting for your check.")
    else:
        _tell([task.created_by], user, task, f"Task completed: {task.title}", task.code, channels=BELL_ONLY)
    return task


@transaction.atomic
def review_task(user, task, approve, comment=""):
    """The reviewer completes the task, or sends it back (comment required)."""
    _require(can_review(user, task), "Only the reviewer can complete or send back a task that is under review.")
    comment = comment.strip()
    if not approve and not comment:
        _refuse({"comment": "Write a comment saying what must be fixed."})
    task.status = Status.COMPLETED if approve else Status.IN_PROGRESS
    task.completed_at = timezone.now() if approve else None
    task.save()
    _system_note(task, user, "Review done: task completed." if approve else "Sent back by the reviewer.")
    if comment:
        TaskComment.objects.create(task=task, created_by=user, text=comment)
    title = f"Task completed: {task.title}" if approve else f"Task sent back: {task.title}"
    _tell([task.owner, task.created_by], user, task, title, comment or task.code)
    return task


@transaction.atomic
def cancel_task(user, task):
    """No real delete: the task is hidden from lists but stays in history."""
    _require(can_cancel(user, task), "Only the person who created this task, or an admin, can cancel it.")
    task.is_active = False
    task.save()
    _system_note(task, user, "Task cancelled.")
    _tell([task.owner], user, task, f"Task cancelled: {task.title}", task.code, channels=BELL_ONLY)


# ---------- comments, actions, links ----------


def add_comment(user, task, text):
    _require(can_see_record(user, task), "You cannot comment on this task.")
    if not text.strip():
        _refuse("Write something before posting the comment.")
    comment = TaskComment.objects.create(task=task, created_by=user, text=text.strip())
    _tell(_people_on(task), user, task, f"New comment: {task.title}", comment.text[:200], channels=BELL_ONLY)
    return comment


def add_action(user, task, title, owner, due_date):
    _require(can_manage(user, task), "Only the owner, the creator, the owner's manager or an admin can add actions.")
    if not title.strip():
        _refuse("Write what has to be done.")
    _check_people(task.company, owner=owner)
    action = TaskAction.objects.create(task=task, created_by=user, title=title.strip(), owner=owner, due_date=due_date)
    _tell([owner], user, task, f"New action for you: {action.title}", f"In {task.code} {task.title}, due {_day(due_date)}.")
    return action


def toggle_action(user, action):
    _require(can_change_action(user, action), "Only the person doing this action, or the task owner, can tick it.")
    action.is_done = not action.is_done
    action.save(update_fields=["is_done"])
    return action


def remove_action(user, action):
    _require(can_manage(user, action.task), "Only the task owner, creator or an admin can remove an action.")
    action.delete()


def add_link(user, task, label, url):
    _require(can_see_record(user, task), "You cannot add links to this task.")
    link = TaskLink(task=task, created_by=user, label=label.strip() or url.strip(), url=url.strip())
    try:
        link.full_clean(exclude=["task"])  # a clear error for a bad web address
    except ValidationError as error:
        _refuse(error.message_dict)
    link.save()
    return link


def can_remove_link(user, link, visible=False):
    return is_person_or_manager(user, link.created_by_id, link.task, visible)


def remove_link(user, link):
    _require(can_remove_link(user, link), "Only the person who added this link, or the task owner, can remove it.")
    link.delete()
