import logging
from datetime import datetime
from urllib.parse import urlsplit

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import F
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django_datatable import CHOICE, DATE, NUMBER, Column, DataTable, table_response

from core.access.mixins import AppAccessRequiredMixin
from core.access.services import companies_for_app
from core.files import services as files

from . import services
from .forms import ActionForm, TaskForm, task_initial
from .models import Task, TaskAction, TaskLink
from .schedule import WEEKDAYS, describe

logger = logging.getLogger(__name__)

LISTS = {
    "mine": ("My tasks", services.my_tasks, "Tasks where you are owner, reviewer or collaborator, or have an action"),
    "assigned": ("Assigned by me", services.assigned_by_me, "Tasks you gave to someone else"),
    "all": ("All tasks", services.visible_tasks, "Every task you are allowed to see"),
    "review": ("For my review", services.waiting_for_my_review, "Tasks sent to you for a check before they are completed"),
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
CALENDAR_YEARS = (2000, 2100)  # months outside this are refused (and the date maths stays safe)
PEOPLE_COLUMNS = [
    Column("first_name", "Person"),
    Column("open_count", "Open", type=NUMBER),
    Column("overdue_count", "Overdue", type=NUMBER),
    Column("done_count", "Done this month", type=NUMBER),
    Column("on_time_percent", "On time %", type=NUMBER),
]
# The dashboard cards: (key in dashboard_numbers, label, list, filter, colour, tooltip)
CARDS = (
    ("overdue", "Overdue", "all", "due_group=overdue", "text-error", "Due date has passed and the task is not completed"),
    ("today", "Due today", "all", "due_group=today", "text-warning", "Open tasks due today"),
    ("week", "Next 7 days", "all", "due_group=week", "text-info", "Open tasks due in the coming 7 days (not today)"),
    ("review", "For my review", "review", "", "text-primary", "Tasks sent to you for a check"),
    ("blocked", "Blocked", "all", "status=blocked", "text-error", "Open tasks marked Blocked"),
)


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

    def company(self, request):
        """The company picked in a "new" form (the user's first one if none is picked), and all their companies."""
        companies = companies_for_app(request.user, "tasks")
        picked = request.POST.get("company") or request.GET.get("company")
        company = companies.filter(pk=picked).first() if picked and picked.isdigit() else companies.first()
        if company is None:
            raise Http404("You have no company to add a task in.")
        return company, companies


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
        context = {"table": table, "title": title, "lists": LISTS, "view": view, "tab": view}
        return table_response(request, table, "tasks/list.html", "tasks/partials/table.html", context)


class CalendarView(TasksView):
    """Tasks on a month grid. Example: /tasks/calendar/?month=2026-11&show=all.
    Prev / Next / Today swap only the grid (HTMX); the address keeps the month, so Close returns here."""

    def get(self, request):
        month_text = request.GET.get("month", "")
        month = timezone.localdate().replace(day=1)
        if month_text:
            try:
                month = datetime.strptime(month_text, "%Y-%m").date()
                if not CALENDAR_YEARS[0] <= month.year <= CALENDAR_YEARS[1]:
                    raise ValueError("year out of range")
            except ValueError:
                logger.warning("Calendar: bad month %r from user %s", month_text, request.user.pk)
                messages.error(
                    request, f"'{month_text}' is not a month like 2026-11 (years {CALENDAR_YEARS[0]} to "
                    f"{CALENDAR_YEARS[1]}). Showing this month instead."
                )
                month = timezone.localdate().replace(day=1)
        show = "mine" if request.GET.get("show") == "mine" else "all"
        context = {
            "title": "Calendar", "lists": LISTS, "tab": "calendar", "show": show,
            "calendar": services.calendar_month(request.user, month.year, month.month, mine=show == "mine"),
            "weekdays": [name[:3] for name in WEEKDAYS],
        }
        # The Back button may ask again for a pushed address (history restore): that needs the whole page.
        only_grid = request.htmx and not request.htmx.history_restore_request
        template = "tasks/partials/calendar.html" if only_grid else "tasks/calendar.html"
        return render(request, template, context)


class DashboardView(TasksView):
    """Counts, a per-person table and two charts, all on tasks this user may see. Example: /tasks/dashboard/."""

    def get(self, request):
        numbers = services.dashboard_numbers(request.user)
        table = DataTable(
            request.GET, services.people_numbers(request.user), PEOPLE_COLUMNS, table_id="people-table",
            default_sort=("-overdue_count", "first_name"), base_url=request.path,
            search_fields=("first_name", "last_name"), search_placeholder="Search people", noun="people",
        )
        cards = [
            {
                "label": label, "count": numbers["cards"][key], "colour": colour, "tooltip": tooltip,
                "url": reverse("tasks:list", args=[list_slug]) + (f"?{query}" if query else ""),
            }
            for key, label, list_slug, query, colour, tooltip in CARDS
        ]
        charts = {
            "status": {"labels": [name for name, _ in numbers["by_status"]], "values": [n for _, n in numbers["by_status"]]},
            "category": {
                "labels": [name for name, _ in numbers["by_category"]], "values": [n for _, n in numbers["by_category"]]
            },
        }
        context = {"table": table, "title": "Dashboard", "lists": LISTS, "tab": "dashboard", "cards": cards, "charts": charts}
        return table_response(request, table, "tasks/dashboard.html", "tasks/partials/people_table.html", context)


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
        "repeats_text": describe(task.recurring_task) if task.recurring_task_id else "",
        "rule_visible": bool(task.recurring_task_id)
        and services.visible_rules(user).filter(pk=task.recurring_task_id).exists(),
        "close_url": close_url(request),
        "as_page": shown_as_page(request),
    }
    template = "tasks/partials/panel.html" if request.htmx else "tasks/detail.html"
    return render(request, template, context, status=status)


def list_behind(request):
    """Address of the list the panel was opened over, or "" when the panel is a page of its own."""
    current = request.headers.get("HX-Current-URL", "")
    path = urlsplit(current).path
    if request.htmx and (path.startswith("/tasks/list/") or path in (reverse("tasks:rules"), reverse("tasks:calendar"))):
        return current
    return ""


def shown_as_page(request):
    """The panel slides over a list; opened by its own address (e.g. from an email) it is a normal page."""
    return not list_behind(request)


def close_url(request, default=""):
    """Where Close goes: back to the list the panel was opened from (reloads it with fresh rows)."""
    return list_behind(request) or default or reverse("tasks:list", args=["mine"])


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
