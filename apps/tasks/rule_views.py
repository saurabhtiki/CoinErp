"""Screens for repeating rules and holidays. The rules themselves live in services.py."""
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import F
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape
from django_datatable import CHOICE, DATE, Column, DataTable, table_response

from . import services
from core.files import services as files

from .forms import HolidayForm, NewRuleParts, RuleActionForm, RuleForm, rule_initial
from .models import Holiday, RecurringAction, RecurringLink, RecurringTask
from .schedule import describe
from .views import LISTS, NEW_TABS, TasksView, close_url, error_text, new_tab_errors, shown_as_page

RULE_COLUMNS = [
    Column("title", "Repeating task"),
    Column("owner_name", "Owner", type=CHOICE),
    Column("frequency", "Repeats", type=CHOICE, choices=dict(RecurringTask.Frequency.choices)),
    Column("is_paused", "Status", type=CHOICE, choices={True: "Paused", False: "Active"}),
]
HOLIDAY_COLUMNS = [
    Column("date", "Date", type=DATE),
    Column("name", "Holiday"),
    Column("company_code", "Company", type=CHOICE),
]
PREVIEW_FIELDS = (*services.SCHEDULE_FIELDS, "start_date", "end_date")
SATURDAY_NAMES = ((1, "1st"), (2, "2nd"), (3, "3rd"), (4, "4th"), (5, "5th"))


class RulesView(TasksView):
    def rule(self, pk):
        """The repeating rule, or 404 if this user may not see it."""
        return get_object_or_404(services.visible_rules(self.request.user), pk=pk)


def rules_url():
    return reverse("tasks:rules")


def rule_panel(request, rule=None, form=None, error="", action_form=None, company=None, companies=(), tab="details",
               parts=None):
    """The rule panel. Tabs: Details (fields with a live preview of the dates) | Actions | Files & links |
    Comments, then the tasks it made. A new rule sends all tabs with one click; on a saved rule each
    tab's change is saved at once."""
    user = request.user
    company = rule.company if rule else company
    can_manage = rule is None or services.can_manage(user, rule, visible=True)
    if form is None:
        initial = rule_initial(rule) if rule else {"owner": user.pk, "start_date": timezone.localdate()}
        form = RuleForm(initial=initial, company=company, is_new=rule is None, read_only=not can_manage)
    frequency = form["frequency"].value()
    context = {
        "rule": rule,
        "form": form,
        "frequency": frequency if frequency in RecurringTask.Frequency.values else RecurringTask.Frequency.MONTHLY,
        "company": company,
        "companies": companies if rule is None and len(companies) > 1 else [],
        "can_manage": can_manage,
        "panel_error": error,
        "close_url": close_url(request, default=rules_url()),
        "as_page": shown_as_page(request),
        "tab": tab if tab in NEW_TABS else "details",
    }
    if rule:
        items = [(item, files.can_remove(item, user)) for item in files.attachments_for(rule)]
        links = list(rule.links.select_related("created_by"))
        context.update(
            repeats_text=describe(rule),
            actions=rule.actions.select_related("owner"),
            action_form=action_form or RuleActionForm(rule=rule),
            tasks_made=services.visible_tasks(user).filter(recurring_task=rule).order_by("-due_date")[:10],
            record=rule, items=items, can_upload=can_manage, links=links, files_count=len(items) + len(links),
            upload_url=reverse("files:record", args=["tasks", "recurringtask", rule.pk]),
            comments=rule.comments.select_related("created_by"),
        )
    else:
        parts = parts or NewRuleParts(company=company)
        tab_errors = new_tab_errors(form, parts)
        context.update(
            parts=parts, people=services.people_of(company), tab_errors=tab_errors,
            tab=next((name for name in NEW_TABS if tab_errors[name]), "details"),
            files_lost=bool(parts.files) and any(tab_errors.values()),
        )
    template = "tasks/partials/rule.html" if request.htmx else "tasks/rule.html"
    return render(request, template, context)


class RuleListView(RulesView):
    def get(self, request):
        rows = services.visible_rules(request.user).annotate(owner_name=F("owner__first_name"))
        table = DataTable(
            request.GET, rows, RULE_COLUMNS, table_id="rules-table", default_sort=("title",), base_url=request.path,
            search_fields=("title", "description"), search_placeholder="Search repeating tasks", noun="repeating tasks",
        )
        context = {
            "table": table, "title": "Repeating tasks", "lists": LISTS, "tab": "rules",
            "is_admin": bool(services.admin_companies(request.user)),
        }
        return table_response(request, table, "tasks/rules.html", "tasks/partials/rules_table.html", context)


class RuleNewView(RulesView):
    def get(self, request):
        company, companies = self.company(request)
        return rule_panel(request, company=company, companies=companies)

    def post(self, request):
        company, companies = self.company(request)
        form = RuleForm(request.POST, company=company, is_new=True)
        parts = NewRuleParts(request.POST, request.FILES, company=company)
        form_ok = form.is_valid()
        if parts.is_valid() and form_ok:  # both checked: every tab shows its errors
            data = dict(form.cleaned_data)
            try:
                rule = services.save_rule(
                    request.user, company, first_comment=data.pop("comment"),
                    actions=parts.actions, links=parts.links, files=parts.files, **data,
                )
            except ValidationError as error:
                if rest := parts.take_service_errors(error):
                    form.add_service_errors(rest)
            else:
                if not request.htmx:
                    return redirect("tasks:rule", pk=rule.pk)
                response = rule_panel(request, rule)
                if shown_as_page(request):
                    response["HX-Push-Url"] = reverse("tasks:rule", args=[rule.pk])
                return response
        return rule_panel(request, form=form, company=company, companies=companies, parts=parts)


class RuleDetailView(RulesView):
    def get(self, request, pk):
        return rule_panel(request, self.rule(pk))

    def post(self, request, pk):
        rule = self.rule(pk)
        form = RuleForm(request.POST, company=rule.company)
        if form.is_valid():
            try:
                services.save_rule(request.user, rule.company, rule, **form.cleaned_data)
            except ValidationError as error:
                form.add_service_errors(error)
            except PermissionDenied as error:
                return rule_panel(request, rule, error=error_text(error))
            else:
                return self.after_rule_change(request, pk)
        return rule_panel(request, rule, form=form)

    def after_rule_change(self, request, pk):
        """Redraw with fresh data; if the rule went out of the user's sight (new owner), back to the list."""
        rule = services.visible_rules(request.user).filter(pk=pk).first()
        if rule is not None:
            return rule_panel(request, rule)
        if request.htmx:
            return HttpResponse(status=204, headers={"HX-Redirect": rules_url()})
        return redirect(rules_url())


class RulePreviewView(RulesView):
    """The line under the form: "First task: Wed 11 Nov 2026 (Oct 2026), then 11 Dec 2026, 11 Jan 2027"."""

    def post(self, request):
        company, _ = self.company(request)
        form = RuleForm(request.POST, company=company)
        form.is_valid()
        if any(name in form.errors for name in PREVIEW_FIELDS):
            return HttpResponse("Fill in the repeat fields to see the dates.")
        values = {name: form.cleaned_data.get(name) for name in PREVIEW_FIELDS}
        is_new = "saved" not in request.POST
        return HttpResponse(escape(services.preview_text(company, is_new=is_new, **values)))


class RulePauseView(RulesView):
    """Pause or resume. From a list row the page reloads; inside the panel the panel is redrawn."""

    def post(self, request, pk):
        rule = self.rule(pk)
        from_list = request.POST.get("from") == "list"
        try:
            services.set_paused(request.user, rule, paused=not rule.is_paused)
        except PermissionDenied as error:
            if from_list:
                return HttpResponse(error_text(error), status=403)
            return rule_panel(request, rule, error=error_text(error))
        if from_list:
            return HttpResponse(status=204, headers={"HX-Refresh": "true"})
        return rule_panel(request, rule)


class RuleActionAddView(RulesView):
    def post(self, request, pk):
        rule = self.rule(pk)
        form = RuleActionForm(request.POST, rule=rule)
        if not form.is_valid():
            return rule_panel(request, rule, action_form=form, tab="actions")
        try:
            services.add_rule_action(request.user, rule, **form.cleaned_data)
        except (ValidationError, PermissionDenied) as error:
            return rule_panel(request, rule, error=error_text(error), tab="actions")
        return rule_panel(request, rule, tab="actions")


class RuleActionRemoveView(RulesView):
    def post(self, request, pk):
        action = get_object_or_404(RecurringAction, pk=pk)
        rule = self.rule(action.recurring_task_id)
        try:
            services.remove_rule_action(request.user, action)
        except PermissionDenied as error:
            return rule_panel(request, rule, error=error_text(error), tab="actions")
        return rule_panel(request, rule, tab="actions")


class RuleLinkAddView(RulesView):
    def post(self, request, pk):
        rule = self.rule(pk)
        try:
            services.add_rule_link(request.user, rule, request.POST.get("label", ""), request.POST.get("url", ""))
        except (ValidationError, PermissionDenied) as error:
            return rule_panel(request, rule, error=error_text(error), tab="files")
        return rule_panel(request, rule, tab="files")


class RuleLinkRemoveView(RulesView):
    def post(self, request, pk):
        link = get_object_or_404(RecurringLink, pk=pk)
        rule = self.rule(link.recurring_task_id)
        try:
            services.remove_rule_link(request.user, link)
        except PermissionDenied as error:
            return rule_panel(request, rule, error=error_text(error), tab="files")
        return rule_panel(request, rule, tab="files")


class RuleCommentView(RulesView):
    def post(self, request, pk):
        rule = self.rule(pk)
        try:
            services.add_rule_comment(request.user, rule, request.POST.get("text", ""))
        except (ValidationError, PermissionDenied) as error:
            return rule_panel(request, rule, error=error_text(error), tab="comment")
        return rule_panel(request, rule, tab="comment")


class RuleRunView(RulesView):
    """The admin's "Create due tasks now" button: the same work as the daily job."""

    def post(self, request):
        try:
            count = services.create_due_tasks(user=request.user)
        except PermissionDenied as error:
            messages.error(request, error_text(error))
        else:
            messages.success(request, f"{count} task{'s' if count != 1 else ''} created." if count else "No task was due: nothing new to create.")
        return redirect(rules_url())


class HolidayListView(TasksView):
    def page(self, request, form=None):
        user = request.user
        rows = services.holidays_for(user).annotate(company_code=F("company__code"))
        table = DataTable(
            request.GET, rows, HOLIDAY_COLUMNS, table_id="holidays-table", default_sort=("date",),
            base_url=request.path, search_fields=("name",), search_placeholder="Search holidays", noun="holidays",
        )
        admin_companies = services.admin_companies(user)
        context = {
            "table": table, "title": "Holidays", "lists": LISTS, "tab": "holidays",
            "admin_company_ids": {company.pk for company in admin_companies},
            "form": form or (HolidayForm(companies=admin_companies) if admin_companies else None),
            "saturdays": [
                (company, [(number, name, number in services.off_saturdays_of(company)) for number, name in SATURDAY_NAMES])
                for company in admin_companies
            ],
        }
        return table_response(request, table, "tasks/holidays.html", "tasks/partials/holidays_table.html", context)

    def get(self, request):
        return self.page(request)

    def post(self, request):
        form = HolidayForm(request.POST, companies=services.admin_companies(request.user))
        if form.is_valid():
            try:
                holiday = services.add_holiday(request.user, **form.cleaned_data)
            except ValidationError as error:
                for field, texts in error.message_dict.items():
                    for text in texts:
                        form.add_error(field, text)
            except PermissionDenied as error:
                form.add_error(None, error_text(error))
            else:
                messages.success(request, f"Holiday added: {holiday}.")
                return redirect("tasks:holidays")
        return self.page(request, form=form)


class HolidayRemoveView(TasksView):
    def post(self, request, pk):
        holiday = get_object_or_404(services.holidays_for(request.user), pk=pk)
        try:
            services.remove_holiday(request.user, holiday)
        except PermissionDenied as error:
            messages.error(request, error_text(error))
        else:
            messages.success(request, f"Holiday removed: {holiday}.")
        return redirect("tasks:holidays")


class SaturdaysView(TasksView):
    def post(self, request):
        company, _ = self.company(request)
        try:
            saturdays = services.set_off_saturdays(request.user, company, request.POST.getlist("saturdays"))
        except (ValidationError, PermissionDenied, ValueError) as error:
            messages.error(request, error_text(error) if not isinstance(error, ValueError) else "Tick the Saturdays from the list.")
        else:
            names = ", ".join(name for number, name in SATURDAY_NAMES if number in saturdays) or "none"
            messages.success(request, f"Off Saturdays of {company}: {names}. New repeating tasks will use this.")
        return redirect("tasks:holidays")
