from django.conf import settings
from django.db import models
from django.db.models import Q

from core.access.models import BaseModel
from core.masters.services import team_user_ids_by_company


class TaskCategory(BaseModel):
    name = models.CharField(max_length=100)

    class Meta(BaseModel.Meta):
        verbose_name_plural = "task categories"
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["company", "name"], name="unique_task_category_per_company")]

    def __str__(self):
        return self.name


def _people_filter(model, user):
    """Rows where the user is owner, reviewer or collaborator, or the owner is in the user's team."""
    involved = (
        Q(owner=user)
        | Q(reviewer=user)
        | Q(pk__in=model.collaborators.through.objects.filter(user=user).values(f"{model._meta.model_name}_id"))
    )
    for company_id, user_ids in team_user_ids_by_company(user).items():
        involved |= Q(company_id=company_id, owner_id__in=user_ids)
    return involved


class Priority(models.TextChoices):
    HIGH = "high", "High"
    MEDIUM = "medium", "Medium"
    LOW = "low", "Low"


class RecurringTask(BaseModel):
    """A repeating rule. It is not a task and has no due date: a daily job makes the tasks from it.

    Example: "GSTR1", monthly, day 11 of the next month -> tasks "GSTR1 - Oct 2026" (due 11 Nov), and so on.
    """

    class Frequency(models.TextChoices):
        DAILY = "daily", "Daily"
        WEEKLY = "weekly", "Weekly"
        MONTHLY = "monthly", "Monthly"
        YEARLY = "yearly", "Yearly"

    class OffDayRule(models.TextChoices):
        PREVIOUS = "previous", "Previous working day"
        NEXT = "next", "Next working day"
        KEEP = "keep", "Keep the date"

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="owned_recurring_tasks")
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="review_recurring_tasks"
    )
    collaborators = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="collaborator_recurring_tasks")
    category = models.ForeignKey(
        "TaskCategory", null=True, blank=True, on_delete=models.PROTECT, related_name="recurring_tasks"
    )
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.MEDIUM)
    frequency = models.CharField(max_length=10, choices=Frequency.choices, default=Frequency.MONTHLY)
    repeat_every = models.PositiveSmallIntegerField(default=1, help_text="1 = every month, 3 = every 3 months.")
    weekday = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Weekly rules: 0 = Monday ... 6 = Sunday.")
    due_day = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text="Monthly and yearly rules: day 1-31. 31 means the last day of the month."
    )
    due_month = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Yearly rules: month 1-12.")
    due_in_next_period = models.BooleanField(default=False, help_text="Example: October's work, due in November.")
    off_day_rule = models.CharField(max_length=10, choices=OffDayRule.choices, default=OffDayRule.PREVIOUS)
    create_days_before = models.PositiveSmallIntegerField(
        default=7, help_text="How many days before its due date the task appears."
    )
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    is_paused = models.BooleanField(default=False)
    skip_before = models.DateField(
        null=True, blank=True, editable=False,
        help_text="Set when the timing is changed: no task with an earlier due date is made any more.",
    )

    class Meta(BaseModel.Meta):
        ordering = ["title"]

    def __str__(self):
        return self.title

    @classmethod
    def involved_filter(cls, user):
        return _people_filter(cls, user)

    def is_managed_by(self, user):
        return self.owner_id == user.pk or self.owner_id in team_user_ids_by_company(user).get(self.company_id, ())


class RecurringAction(models.Model):
    """An action copied to every task of a rule. Example: "Send data to CA", Amar, 3 days before the due date."""

    recurring_task = models.ForeignKey(RecurringTask, on_delete=models.CASCADE, related_name="actions")
    title = models.CharField(max_length=200)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="recurring_actions")
    days_before_due = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["-days_before_due", "pk"]

    def __str__(self):
        return self.title


class Holiday(BaseModel):
    """A day off for one company. Sundays and the company's off Saturdays are not listed here."""

    date = models.DateField()
    name = models.CharField(max_length=100)

    class Meta(BaseModel.Meta):
        ordering = ["date"]
        constraints = [models.UniqueConstraint(fields=["company", "date"], name="unique_holiday_per_company_date")]

    def __str__(self):
        return f"{self.date:%d %b %Y} {self.name}"


def default_off_saturdays():
    return [2, 4]


class OffDaySetting(BaseModel):
    """Which Saturdays of the month are off in a company. Example: [2, 4]. Sunday is always off."""

    off_saturdays = models.JSONField(default=default_off_saturdays)

    class Meta(BaseModel.Meta):
        constraints = [models.UniqueConstraint(fields=["company"], name="unique_off_day_setting_per_company")]

    def __str__(self):
        return f"Off Saturdays of {self.company}"


class Task(BaseModel):
    Priority = Priority

    class Status(models.TextChoices):
        NOT_STARTED = "not_started", "Not Started"
        IN_PROGRESS = "in_progress", "In Progress"
        BLOCKED = "blocked", "Blocked"
        UNDER_REVIEW = "under_review", "Under Review"
        COMPLETED = "completed", "Completed"

    number = models.PositiveIntegerField(editable=False, help_text="Runs 1, 2, 3... inside each company.")
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="owned_tasks",
        help_text="The person who must get this task done.",
    )
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="review_tasks",
        help_text="Optional. If set, the task goes to this person for a check before it is completed.",
    )
    collaborators = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True, related_name="collaborator_tasks",
        help_text="Can view the task, comment and add files.",
    )
    category = models.ForeignKey(TaskCategory, null=True, blank=True, on_delete=models.PROTECT, related_name="tasks")
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.MEDIUM)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NOT_STARTED)
    due_date = models.DateField()
    completed_at = models.DateTimeField(null=True, blank=True, editable=False)
    due_date_changes = models.PositiveIntegerField(default=0, editable=False)
    recurring_task = models.ForeignKey(
        RecurringTask, null=True, blank=True, editable=False, on_delete=models.PROTECT, related_name="tasks",
        help_text="The repeating rule that made this task. Empty for a one-time task.",
    )
    period_label = models.CharField(max_length=40, blank=True, editable=False, help_text='Example: "Oct 2026".')
    period_start = models.DateField(null=True, blank=True, editable=False)

    class Meta(BaseModel.Meta):
        ordering = ["due_date", "number"]
        constraints = [
            models.UniqueConstraint(fields=["company", "number"], name="unique_task_number_per_company"),
            # one task per rule and period: the daily job can never make the same task twice
            models.UniqueConstraint(
                fields=["recurring_task", "period_start", "period_label"], name="unique_task_per_rule_and_period"
            ),
        ]

    def __str__(self):
        return f"{self.code} {self.title}"

    @property
    def code(self):
        """Number as people say it. Example: 51 -> TSK-0051."""
        return f"TSK-{self.number:04d}"

    @property
    def is_completed(self):
        return self.status == self.Status.COMPLETED

    @classmethod
    def involved_filter(cls, user):
        """Besides its creator, a task is seen by its owner, reviewer, collaborators, anyone with an
        action on it, and the managers of its owner."""
        return _people_filter(cls, user) | Q(pk__in=TaskAction.objects.filter(owner=user).values("task_id"))

    def is_managed_by(self, user):
        """The owner and the owner's managers run a task, even if someone else created it."""
        return self.owner_id == user.pk or self.owner_id in team_user_ids_by_company(user).get(self.company_id, ())


class TaskPart(models.Model):
    """Base for the small things that hang on a task: who added it and when."""

    task = models.ForeignKey(Task, on_delete=models.CASCADE)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+", editable=False
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True
        ordering = ["created_at", "pk"]


class TaskAction(TaskPart):
    """A small step inside a task. Example: "Send data to CA", Amar, 18 Nov."""

    title = models.CharField(max_length=200)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="task_actions")
    due_date = models.DateField()
    is_done = models.BooleanField(default=False)

    class Meta(TaskPart.Meta):
        default_related_name = "actions"

    def __str__(self):
        return self.title


class TaskComment(TaskPart):
    text = models.TextField()
    is_system = models.BooleanField(default=False, help_text='Written by the app, e.g. "Due date moved".')

    class Meta(TaskPart.Meta):
        default_related_name = "comments"

    def __str__(self):
        return self.text[:50]


class TaskLink(TaskPart):
    """A web link kept with the task, e.g. a Google Drive file."""

    label = models.CharField(max_length=200)
    url = models.URLField(max_length=500)

    class Meta(TaskPart.Meta):
        default_related_name = "links"

    def __str__(self):
        return self.label
