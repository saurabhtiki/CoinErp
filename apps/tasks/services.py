"""Tasks business rules. Who may see or change a task is asked from core.access, never decided here.

Example:
    task = create_task(saurabh, acme, title="GSTR1", owner=het, due_date=date(2026, 11, 18))
    update_task(het, task, {"due_date": date(2026, 11, 25)}, comment="Data came late")  # counter +1
    mark_done(het, task)  # Completed, or Under Review if the task has a reviewer
"""
import logging
from datetime import timedelta
from itertools import takewhile

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Case, Count, F, IntegerField, Max, Q, Value, When
from django.urls import reverse
from django.utils import timezone

from core.access.services import (
    can_manage_record,
    can_see_record,
    companies_for_app,
    is_app_admin,
    is_person_or_admin,
    is_person_or_manager,
    manages_visible_record,
    team_rows,
    users_for_app,
)
from core.masters.models import Company
from core.notifications.models import NotificationLog
from core.notifications.services import notify

from . import schedule
from .models import (
    Holiday,
    OffDaySetting,
    RecurringAction,
    RecurringTask,
    Task,
    TaskAction,
    TaskCategory,
    TaskComment,
    TaskLink,
    default_off_saturdays,
)

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


def waiting_for_my_review(user):
    """Tasks sent to me for a check."""
    return visible_tasks(user).filter(reviewer=user, status=Status.UNDER_REVIEW)


# ---------- dashboard ----------


def dashboard_numbers(user, today=None):
    """Everything the Tasks dashboard shows, counted only on tasks this user may see.

    Example: {"cards": {"overdue": 3, "today": 1, "week": 4, "review": 2, "blocked": 1},
              "by_status": [("Not Started", 5), ...], "by_category": [("MIS", 3), ...]}
    """
    today = today or timezone.localdate()
    # Same rows as visible_tasks(), without the list's extra columns, so the counts group cleanly.
    open_tasks = Task.objects.for_user(user).filter(is_active=True).exclude(status=Status.COMPLETED).order_by()
    cards = open_tasks.aggregate(
        overdue=Count("pk", filter=Q(due_date__lt=today)),
        today=Count("pk", filter=Q(due_date=today)),
        week=Count("pk", filter=Q(due_date__gt=today, due_date__lte=today + timedelta(days=7))),
        blocked=Count("pk", filter=Q(status=Status.BLOCKED)),
        review=Count("pk", filter=Q(reviewer=user, status=Status.UNDER_REVIEW)),
    )
    status_names = dict(Status.choices)
    status_order = list(status_names)
    by_status = sorted(
        ((row["status"], row["total"]) for row in open_tasks.values("status").annotate(total=Count("pk"))),
        key=lambda item: status_order.index(item[0]),
    )
    by_category = [
        (row["category__name"] or "No category", row["total"])
        for row in open_tasks.values("category__name").annotate(total=Count("pk")).order_by("-total", "category__name")
    ]
    by_status = [(status_names[status], total) for status, total in by_status]
    return {"cards": cards, "by_status": by_status, "by_category": by_category}


def people_numbers(user, today=None):
    """One row per person whose tasks I look after (me, my team, or everyone where I am admin):
    open, overdue, done this month and on-time % (done by the due date, out of done this month).

    Example: Het -> open 4, overdue 1, done 8, on time 75. No task done this month -> on time None ("–").
    """
    today = today or timezone.localdate()
    month_start = today.replace(day=1)
    team_tasks = team_rows(Task.objects.filter(is_active=True), user)
    team_task_ids = team_tasks.values("pk")
    mine = Q(owned_tasks__in=team_task_ids)
    is_open = mine & ~Q(owned_tasks__status=Status.COMPLETED)
    done = mine & Q(owned_tasks__status=Status.COMPLETED, owned_tasks__completed_at__date__gte=month_start)
    on_time = done & Q(owned_tasks__completed_at__date__lte=F("owned_tasks__due_date"))
    rows = User.objects.filter(pk__in=team_tasks.values("owner")).annotate(
        open_count=Count("owned_tasks", filter=is_open, distinct=True),
        overdue_count=Count("owned_tasks", filter=is_open & Q(owned_tasks__due_date__lt=today), distinct=True),
        done_count=Count("owned_tasks", filter=done, distinct=True),
        on_time_count=Count("owned_tasks", filter=on_time, distinct=True),
    )
    return rows.annotate(
        on_time_percent=Case(
            When(done_count=0, then=Value(None)),
            default=F("on_time_count") * 100 / F("done_count"),
            output_field=IntegerField(),
        )
    )


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


def _new_task(company, created_by, collaborators, **fields):
    """Save a task with the company's next number. Call inside a transaction."""
    Company.objects.select_for_update().get(pk=company.pk)  # one new task at a time per company: no twin numbers
    last_number = Task.objects.filter(company=company).aggregate(last=Max("number"))["last"] or 0
    task = Task.objects.create(company=company, created_by=created_by, number=last_number + 1, **fields)
    task.collaborators.set(collaborators)
    return task


@transaction.atomic
def create_task(user, company, *, title, owner, due_date, category=None, priority=Task.Priority.MEDIUM,
                reviewer=None, collaborators=(), description="", first_comment=""):
    collaborators = [person for person in collaborators if person.pk != owner.pk]
    _check_people(company, owner=owner, reviewer=reviewer, collaborators=collaborators)
    if category is not None and category.company_id != company.pk:
        _refuse({"category": f"Pick a category of {company}."})
    task = _new_task(
        company, user, collaborators, title=title, description=description, owner=owner, reviewer=reviewer,
        category=category, priority=priority, due_date=due_date,
    )
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


# ---------- holidays and off Saturdays ----------

ADMIN_ONLY = "Only an admin of Tasks in {company} can change its holidays and off Saturdays."


def is_admin_of(user, company):
    """An admin of Tasks in this company (sees every task there). Asked from core.access."""
    return is_app_admin(user, Task.access_app_code(), company.pk)


def admin_companies(user):
    """Companies where the user is the Tasks admin: there they keep the holidays and may run the daily job."""
    return [company for company in companies_for_app(user, Task.access_app_code()) if is_admin_of(user, company)]


def holidays_for(user):
    """Holidays of every company where the user can open Tasks."""
    return Holiday.objects.filter(company__in=companies_for_app(user, Task.access_app_code()))


def off_saturdays_of(company):
    setting = OffDaySetting.objects.filter(company=company).first()
    return setting.off_saturdays if setting else default_off_saturdays()


def off_days_of(company):
    """The company's days off, for the date maths in schedule.py."""
    return schedule.OffDays(
        saturdays=frozenset(off_saturdays_of(company)),
        holidays=frozenset(Holiday.objects.filter(company=company).values_list("date", flat=True)),
    )


def add_holiday(user, company, date, name):
    _require(is_admin_of(user, company), ADMIN_ONLY.format(company=company))
    if not name.strip():
        _refuse({"name": "Write the name of the holiday, e.g. Diwali."})
    if Holiday.objects.filter(company=company, date=date).exists():
        _refuse({"date": f"{_day(date)} is already a holiday of {company}."})
    return Holiday.objects.create(company=company, created_by=user, date=date, name=name.strip())


def remove_holiday(user, holiday):
    _require(is_admin_of(user, holiday.company), ADMIN_ONLY.format(company=holiday.company))
    holiday.delete()


def set_off_saturdays(user, company, saturdays):
    """Example: set_off_saturdays(boss, acme, [1, 3]). Only tasks made after this use the new days."""
    _require(is_admin_of(user, company), ADMIN_ONLY.format(company=company))
    saturdays = sorted({int(number) for number in saturdays})
    if any(number not in range(1, 6) for number in saturdays):
        _refuse("Saturdays are numbered 1 to 5 (1st to 5th of the month).")
    setting = OffDaySetting.objects.filter(company=company).first() or OffDaySetting(company=company, created_by=user)
    setting.off_saturdays = saturdays
    setting.save()
    return saturdays


# ---------- repeating rules ----------

SCHEDULE_FIELDS = ("frequency", "repeat_every", "weekday", "due_day", "due_month", "due_in_next_period", "off_day_rule")
RULE_FIELDS = (
    "title", "description", "owner", "reviewer", "category", "priority", *SCHEDULE_FIELDS,
    "create_days_before", "start_date", "end_date",
)
RULE_MANAGERS = "Only the owner, the creator, the owner's manager or an admin can change this repeating task."
Frequency = RecurringTask.Frequency
TITLE_LENGTH = Task._meta.get_field("title").max_length


def visible_rules(user):
    return RecurringTask.objects.for_user(user).filter(is_active=True)


def _check_schedule(rule):
    """Each frequency needs its own fields. Fields of other frequencies are emptied."""
    errors = {}
    if not rule.repeat_every or rule.repeat_every < 1:
        errors["repeat_every"] = "Repeat every 1 or more (1 = every time, 3 = every third)."
    if rule.frequency == Frequency.WEEKLY and rule.weekday is None:
        errors["weekday"] = "Pick the weekday the task is due."
    if rule.frequency in (Frequency.MONTHLY, Frequency.YEARLY) and not rule.due_day:
        errors["due_day"] = "Pick the day of the month the task is due."
    if rule.frequency == Frequency.YEARLY and not rule.due_month:
        errors["due_month"] = "Pick the month the task is due."
    if rule.end_date and rule.end_date < rule.start_date:
        errors["end_date"] = "The end date cannot be before the start date."
    if errors:
        _refuse(errors)
    if rule.frequency != Frequency.WEEKLY:
        rule.weekday = None
    if rule.frequency not in (Frequency.MONTHLY, Frequency.YEARLY):
        rule.due_day = None
    if rule.frequency != Frequency.YEARLY:
        rule.due_month = None
    if rule.frequency == Frequency.DAILY:
        rule.due_in_next_period = False


@transaction.atomic
def save_rule(user, company, rule=None, *, collaborators=(), **fields):
    """Make or change a repeating rule. Tasks already made are never touched.

    Example: save_rule(saurabh, acme, title="GSTR1", owner=het, frequency="monthly", due_day=11,
                       due_in_next_period=True)
    """
    fields = {name: value for name, value in fields.items() if name in RULE_FIELDS}
    is_new = rule is None
    if is_new:
        rule = RecurringTask(company=company, created_by=user)
        if not fields.get("start_date"):
            fields["start_date"] = timezone.localdate()
    else:
        _require(can_manage(user, rule), RULE_MANAGERS)
    old_schedule = [getattr(rule, name) for name in (*SCHEDULE_FIELDS, "start_date")]
    for name, value in fields.items():
        setattr(rule, name, value)
    collaborators = [person for person in collaborators if person.pk != rule.owner_id]
    _check_people(rule.company, owner=rule.owner, reviewer=rule.reviewer, collaborators=collaborators)
    if rule.category is not None and rule.category.company_id != rule.company_id:
        _refuse({"category": f"Pick a category of {rule.company}."})
    _check_schedule(rule)
    if not is_new and old_schedule != [getattr(rule, name) for name in (*SCHEDULE_FIELDS, "start_date")]:
        # a new timing counts from today: it must not fill the past with tasks under the new timing.
        # The start date stays: it also fixes where the periods begin (e.g. which months make a quarter).
        rule.skip_before = timezone.localdate()
    rule.save()
    rule.collaborators.set(collaborators)
    return rule


def set_paused(user, rule, paused):
    """A paused rule makes no new tasks. Its open tasks stay as they are."""
    _require(can_manage(user, rule), RULE_MANAGERS)
    rule.is_paused = paused
    if not paused:
        rule.skip_before = timezone.localdate()  # periods missed during the pause are not made after the resume
    rule.save()
    return rule


def add_rule_action(user, rule, title, owner, days_before_due=0):
    _require(can_manage(user, rule), RULE_MANAGERS)
    if not title.strip():
        _refuse("Write what has to be done.")
    _check_people(rule.company, owner=owner)
    return RecurringAction.objects.create(
        recurring_task=rule, title=title.strip(), owner=owner, days_before_due=days_before_due or 0
    )


def remove_rule_action(user, action):
    _require(can_manage(user, action.recurring_task), RULE_MANAGERS)
    action.delete()


def upcoming(rule, off_days, count=3, today=None):
    """The next periods due today or later. `rule` may be unsaved (the form's live preview)."""
    today = today or timezone.localdate()
    found = []
    for period in schedule.periods(rule, off_days):
        if period.due >= today:
            found.append(period)
            if len(found) == count:
                break
    return found


def preview_text(company, is_new=False, **fields):
    """Example: "First task: Wed 11 Nov 2026 (Oct 2026), then 11 Dec 2026, 11 Jan 2027".

    A new rule that starts in the past also says how many earlier tasks the job will make.
    """
    rule = RecurringTask(company=company, **{name: value for name, value in fields.items() if name in SCHEDULE_FIELDS})
    rule.start_date = fields.get("start_date") or timezone.localdate()
    rule.end_date = fields.get("end_date")
    try:
        _check_schedule(rule)
    except ValidationError as error:
        return " ".join(error.messages)
    off_days, today = off_days_of(company), timezone.localdate()
    found = upcoming(rule, off_days, today=today)
    if not found:
        return "No task will be made: the end date comes before the first due date."
    first, later = found[0], found[1:]
    text = f"First task: {first.due:%a %d %b %Y} ({first.label})"
    if later:
        text += ", then " + ", ".join(_day(period.due) for period in later)
    if is_new:
        earlier = sum(1 for _ in takewhile(lambda period: period.due < today, schedule.periods(rule, off_days)))
        if earlier:
            text += (
                f". The start date is in the past: {earlier} earlier task{'s' if earlier != 1 else ''}"
                " (already overdue) will also be made."
            )
    return text


def _make_task(rule, period):
    task = _new_task(
        rule.company, rule.created_by, rule.collaborators.all(),
        title=f"{rule.title[:TITLE_LENGTH - len(period.label) - 3]} - {period.label}",  # the period is never cut off
        description=rule.description, owner=rule.owner, reviewer=rule.reviewer, category=rule.category,
        priority=rule.priority, due_date=period.due, recurring_task=rule, period_label=period.label,
        period_start=period.start,
    )
    TaskAction.objects.bulk_create(
        TaskAction(
            task=task, created_by=rule.created_by, title=action.title, owner=action.owner,
            due_date=period.due - timedelta(days=action.days_before_due),
        )
        for action in rule.actions.all()
    )
    notify(  # bell only: a daily rule must not send a mail every day
        rule.owner, f"New task for you: {task.title}", f"{task.code}, due {_day(period.due)}.",
        channels=BELL_ONLY, link=task_link(task),
    )
    return task


@transaction.atomic
def _make_due_tasks(rule, today, off_days):
    """Tasks of one rule whose time has come and that do not exist yet (also periods missed on earlier days)."""
    Company.objects.select_for_update().get(pk=rule.company_id)  # the job and the button never run a rule together
    made = set(Task.objects.filter(recurring_task=rule).values_list("period_start", "period_label"))
    count = 0
    for period in schedule.periods(rule, off_days):
        if period.due - timedelta(days=rule.create_days_before) > today:
            break
        if (period.start, period.label) not in made:
            _make_task(rule, period)
            count += 1
    return count


def create_due_tasks(today=None, user=None):
    """The daily job (also the admin's "Create due tasks now" button). Returns how many tasks were made.

    With a user, only the rules of companies where that user is the Tasks admin are run.
    Running it twice makes nothing new. One broken rule is logged and does not stop the others.
    """
    today = today or timezone.localdate()
    rules = RecurringTask.objects.filter(is_active=True, is_paused=False).select_related("company", "owner", "created_by")
    if user is not None:
        companies = admin_companies(user)
        _require(companies, "Only an admin of Tasks can create the due tasks now.")
        rules = rules.filter(company__in=companies)
    off_days, count = {}, 0
    for rule in rules:
        try:
            if rule.company_id not in off_days:
                off_days[rule.company_id] = off_days_of(rule.company)
            count += _make_due_tasks(rule, today, off_days[rule.company_id])
        except Exception:  # noqa: BLE001  one bad rule must not stop the rest; the full error goes to the log
            logger.exception("Repeating task %s (%s) could not make its tasks", rule.pk, rule.title)
    logger.info("Repeating tasks: %s task(s) made for %s", count, today)
    return count
