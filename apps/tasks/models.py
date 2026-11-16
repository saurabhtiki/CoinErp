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


class Task(BaseModel):
    class Priority(models.TextChoices):
        HIGH = "high", "High"
        MEDIUM = "medium", "Medium"
        LOW = "low", "Low"

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

    class Meta(BaseModel.Meta):
        ordering = ["due_date", "number"]
        constraints = [models.UniqueConstraint(fields=["company", "number"], name="unique_task_number_per_company")]

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
        involved = (
            Q(owner=user)
            | Q(reviewer=user)
            | Q(pk__in=cls.collaborators.through.objects.filter(user=user).values("task_id"))
            | Q(pk__in=TaskAction.objects.filter(owner=user).values("task_id"))
        )
        for company_id, user_ids in team_user_ids_by_company(user).items():
            involved |= Q(company_id=company_id, owner_id__in=user_ids)
        return involved

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
