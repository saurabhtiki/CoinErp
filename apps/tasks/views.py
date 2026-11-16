import logging

from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import F
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django_datatable import CHOICE, DATE, Column, DataTable, table_response

from core.access.mixins import AppAccessRequiredMixin
from core.access.services import companies_for_app
from core.files import services as files

from . import services
from .forms import ActionForm, TaskForm, task_initial
from .models import Task, TaskAction, TaskLink

logger = logging.getLogger(__name__)

LISTS = {
    "mine": ("My tasks", services.my_tasks, "Tasks where you are owner, reviewer or collaborator, or have an action"),
    "assigned": ("Assigned by me", services.assigned_by_me, "Tasks you gave to someone else"),
    "all": ("All tasks", services.visible_tasks, "Every task you are allowed to see"),
}
COLUMNS = [
    Column("number", "No."),
    Column("title", "Task"),
    Column("owner_name", "Owner", type=CHOICE),
    Column("category_name", "Category", type=CHOICE),
    Column("priority", "Priority", type=CHOICE, choices=dict(Task.Priority.choices)),
    Column("status", "Status", type=CHOICE, choices=dict(Task.Status.choices)),
    Column("due_date", "Due date", type=DATE),
    Column("due_group", "When", type=CHOICE, choices=services.DUE_GROUPS),
]
SHORTCUTS = (
    ("All", "due_group", "", "Show every task"),
    ("Due today", "due_group", "today", "Only tasks due today"),
    ("Next 7 days", "due_group", "week", "Only tasks due in the coming 7 days"),
    ("Overdue", "due_group", "overdue", "Only tasks that are late"),
)
TABS = ("actions", "files", "comments")


class TasksView(AppAccessRequiredMixin, View):
    app_code = "tasks"

    def after_change(self, request, pk, tab="actions"):
        """Redraw the panel with fresh data. If the change took the task out of the user's sight
        (e.g. they gave it to someone outside their team), go back to the list instead."""
        task = services.visible_tasks(request.user).filter(pk=pk).first()
        if task is not None:
            return panel(request, task, tab=tab)
        target = close_url(request)
        if request.htmx:
            return HttpResponse(status=204, headers={"HX-Redirect": target})
        return redirect(target)

    def task(self, pk):
        """The task, or 404 if this user may not see it."""
        return get_object_or_404(services.visible_tasks(self.request.user), pk=pk)


class TaskListView(TasksView):
    """My tasks / Assigned by me / All tasks. Example: /tasks/list/mine/."""

    def get(self, request, view):
        if view not in LISTS:
            raise Http404("No such task list.")
        title, rows_for, _ = LISTS[view]
        rows = rows_for(request.user).annotate(
            owner_name=F("owner__first_name"), category_name=F("category__name")
        )
        table = DataTable(
            request.GET, rows, COLUMNS, table_id="tasks-table", default_sort=("due_date",), base_url=request.path,
            search_fields=("title", "description"), search_placeholder="Search tasks", shortcuts=SHORTCUTS,
            noun="tasks",
        )
        context = {"table": table, "title": title, "lists": LISTS, "view": view}
        return table_response(request, table, "tasks/list.html", "tasks/partials/table.html", context)


def panel(request, task, form=None, tab="actions", error="", action_form=None, status=200):
    """The task panel: fields on top, then Actions / Files / Comments."""
    user = request.user
    # The task came through visible_tasks(), so the rights below need no more "may they see it?" queries.
    can_manage = services.can_manage(user, task, visible=True)
    items = [(item, files.can_remove(item, user)) for item in files.attachments_for(task)]
    links = [
        (link, services.can_remove_link(user, link, visible=True)) for link in task.links.select_related("created_by")
    ]
    actions = [
        (action, services.can_change_action(user, action, visible=True))
        for action in task.actions.select_related("owner")
    ]
    context = {
        "task": task,
        "form": form or TaskForm(initial=task_initial(task), company=task.company, is_new=False, read_only=not can_manage),
        "can_manage": can_manage,
        "can_cancel": services.can_cancel(user, task, visible=True),
        "can_review": services.can_review(user, task, visible=True),
        "can_done": can_manage and task.status not in (Task.Status.COMPLETED, Task.Status.UNDER_REVIEW),
        "open_actions": services.open_actions(task),
        "actions": actions,
        "action_form": action_form or ActionForm(task=task),
        "links": links,
        "files_count": len(items) + len(links),
        "comments": task.comments.select_related("created_by"),
        "items": items,
        "upload_url": reverse("files:record", args=["tasks", "task", task.pk]),
        "tab": tab if tab in TABS else "actions",
        "panel_error": error,
        "today": timezone.localdate(),
        "close_url": close_url(request),
        "as_page": shown_as_page(request),
    }
    template = "tasks/partials/panel.html" if request.htmx else "tasks/detail.html"
    return render(request, template, context, status=status)


def shown_as_page(request):
    """The panel slides over a list; opened by its own address (e.g. from an email) it is a normal page."""
    return not (request.htmx and "/tasks/list/" in request.headers.get("HX-Current-URL", ""))


def close_url(request):
    """Where Close goes: back to the list the panel was opened from (reloads it with fresh rows)."""
    current = request.headers.get("HX-Current-URL", "")
    if request.htmx and "/tasks/list/" in current:
        return current
    return reverse("tasks:list", args=["mine"])


def error_text(error):
    if isinstance(error, ValidationError):
        return " ".join(error.messages)
    return str(error) or "You are not allowed to do this."


class TaskDetailView(TasksView):
    def get(self, request, pk):
        return panel(request, self.task(pk), tab=request.GET.get("tab", "actions"))

    def post(self, request, pk):
        task = self.task(pk)
        form = TaskForm(request.POST, company=task.company, is_new=False)
        if form.is_valid():
            data = dict(form.cleaned_data)
            comment, collaborators = data.pop("comment"), list(data.pop("collaborators"))
            try:
                services.update_task(request.user, task, data, comment=comment, collaborators=collaborators)
            except ValidationError as error:
                form.add_service_errors(error)
            except PermissionDenied as error:
                return panel(request, task, error=error_text(error))
            else:
                return self.after_change(request, pk)
        return panel(request, task, form=form)


class TaskNewView(TasksView):
    def company(self, request):
        companies = companies_for_app(request.user, "tasks")
        picked = request.POST.get("company") or request.GET.get("company")
        company = companies.filter(pk=picked).first() if picked and picked.isdigit() else companies.first()
        if company is None:
            raise Http404("You have no company to add a task in.")
        return company, companies

    def render(self, request, form, company, companies):
        context = {
            "form": form, "company": company, "companies": companies if companies.count() > 1 else [],
            "close_url": close_url(request), "as_page": shown_as_page(request),
        }
        template = "tasks/partials/new.html" if request.htmx else "tasks/new.html"
        return render(request, template, context)

    def get(self, request):
        company, companies = self.company(request)
        initial = {"owner": request.user.pk, "due_date": timezone.localdate()}
        if "title" in request.GET:  # the company was switched: keep what was typed
            initial.update({name: request.GET.get(name) for name in ("title", "due_date", "priority", "description")})
        return self.render(request, TaskForm(initial=initial, company=company, is_new=True), company, companies)

    def post(self, request):
        company, companies = self.company(request)
        form = TaskForm(request.POST, company=company, is_new=True)
        if form.is_valid():
            data = dict(form.cleaned_data)
            try:
                task = services.create_task(request.user, company, first_comment=data.pop("comment"), **data)
            except ValidationError as error:
                form.add_service_errors(error)
            else:
                if not request.htmx:
                    return redirect("tasks:detail", pk=task.pk)
                response = panel(request, task)
                if shown_as_page(request):
                    response["HX-Push-Url"] = reverse("tasks:detail", args=[task.pk])
                return response
        return self.render(request, form, company, companies)


class TaskDoneView(TasksView):
    """Done button. From a list row the page reloads; inside the panel the panel is redrawn."""

    def post(self, request, pk):
        task = self.task(pk)
        from_list = request.POST.get("from") == "list"
        try:
            services.mark_done(request.user, task)
        except (ValidationError, PermissionDenied) as error:
            if from_list:
                return HttpResponse(error_text(error), status=403)
            return panel(request, task, error=error_text(error))
        if from_list:
            return HttpResponse(status=204, headers={"HX-Refresh": "true"})
        return self.after_change(request, pk)


class TaskReviewView(TasksView):
    def post(self, request, pk):
        task = self.task(pk)
        try:
            services.review_task(
                request.user, task, approve=request.POST.get("decision") == "complete",
                comment=request.POST.get("comment", ""),
            )
        except (ValidationError, PermissionDenied) as error:
            return panel(request, task, error=error_text(error))
        return self.after_change(request, pk)


class TaskCancelView(TasksView):
    def post(self, request, pk):
        task = self.task(pk)
        try:
            services.cancel_task(request.user, task)
        except PermissionDenied as error:
            return panel(request, task, error=error_text(error))
        target = close_url(request)
        if request.htmx:
            return HttpResponse(status=204, headers={"HX-Redirect": target})
        return redirect(target)


class TaskCommentView(TasksView):
    def post(self, request, pk):
        task = self.task(pk)
        try:
            services.add_comment(request.user, task, request.POST.get("text", ""))
        except (ValidationError, PermissionDenied) as error:
            return panel(request, task, tab="comments", error=error_text(error))
        return panel(request, task, tab="comments")


class TaskActionAddView(TasksView):
    def post(self, request, pk):
        task = self.task(pk)
        form = ActionForm(request.POST, task=task)
        if not form.is_valid():
            return panel(request, task, action_form=form)
        try:
            services.add_action(request.user, task, **form.cleaned_data)
        except (ValidationError, PermissionDenied) as error:
            return panel(request, task, error=error_text(error))
        return panel(request, task)


class TaskActionView(TasksView):
    """Tick or remove one action."""

    def post(self, request, pk, change):
        if change not in ("toggle", "remove"):
            raise Http404("No such change.")
        action = get_object_or_404(TaskAction, pk=pk)
        task = self.task(action.task_id)
        try:
            if change == "toggle":
                services.toggle_action(request.user, action)
            else:
                services.remove_action(request.user, action)
        except PermissionDenied as error:
            return panel(request, task, error=error_text(error))
        return panel(request, task)


class TaskLinkAddView(TasksView):
    def post(self, request, pk):
        task = self.task(pk)
        try:
            services.add_link(request.user, task, request.POST.get("label", ""), request.POST.get("url", ""))
        except (ValidationError, PermissionDenied) as error:
            return panel(request, task, tab="files", error=error_text(error))
        return panel(request, task, tab="files")


class TaskLinkRemoveView(TasksView):
    def post(self, request, pk):
        link = get_object_or_404(TaskLink, pk=pk)
        task = self.task(link.task_id)
        try:
            services.remove_link(request.user, link)
        except PermissionDenied as error:
            return panel(request, task, tab="files", error=error_text(error))
        return panel(request, task, tab="files")
