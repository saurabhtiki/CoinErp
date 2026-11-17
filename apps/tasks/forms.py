import calendar
from datetime import date

from django import forms
from django.core.exceptions import ValidationError

from core.masters.models import Company

from . import services
from .models import RecurringTask, Task
from .schedule import LAST_DAY, WEEKDAYS

INPUT = "input input-sm w-full"
SELECT = "select select-sm w-full"
TEXTAREA = "textarea textarea-sm w-full"


def person_name(user):
    return user.get_full_name() or user.email


class PersonField(forms.ModelChoiceField):
    def label_from_instance(self, user):
        return person_name(user)


class PeopleField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, user):
        return person_name(user)


def date_input():
    return forms.DateInput(format="%Y-%m-%d", attrs={"type": "date", "class": INPUT})


class TaskForm(forms.Form):
    """Fields of one task. Saving goes through services, so the rules live in one place."""

    title = forms.CharField(max_length=200, widget=forms.TextInput(attrs={"class": INPUT}))
    owner = PersonField(queryset=None, widget=forms.Select(attrs={"class": SELECT}),
                        help_text="The person who must get this done.")
    due_date = forms.DateField(widget=date_input())
    category = forms.ModelChoiceField(queryset=None, required=False, widget=forms.Select(attrs={"class": SELECT}))
    priority = forms.ChoiceField(choices=Task.Priority.choices, initial=Task.Priority.MEDIUM,
                                 widget=forms.Select(attrs={"class": SELECT}))
    reviewer = PersonField(queryset=None, required=False, empty_label="None",
                           widget=forms.Select(attrs={"class": SELECT}),
                           help_text="Optional. Checks the work before the task is completed.")
    status = forms.ChoiceField(choices=Task.Status.choices, widget=forms.Select(attrs={"class": SELECT}))
    collaborators = PeopleField(queryset=None, required=False, widget=forms.CheckboxSelectMultiple,
                                help_text="Can view the task, comment and add files.")
    description = forms.CharField(required=False, widget=forms.Textarea(attrs={"class": TEXTAREA, "rows": 3}))
    comment = forms.CharField(required=False, widget=forms.Textarea(attrs={"class": TEXTAREA, "rows": 2}))

    def __init__(self, *args, company, is_new, read_only=False, **kwargs):
        super().__init__(*args, **kwargs)
        people = services.people_of(company)
        for name in ("owner", "reviewer", "collaborators"):
            self.fields[name].queryset = people
        self.fields["category"].queryset = services.categories_of(company)
        if is_new:
            del self.fields["status"]
            self.fields["comment"].label = "First comment (optional)"
        else:
            self.fields["comment"].label = "Comment (needed if you change the due date or set Blocked)"
        if read_only:
            for field in self.fields.values():
                field.disabled = True

    def add_service_errors(self, error):
        """Show a services ValidationError next to the right field (or on top)."""
        if hasattr(error, "error_dict"):
            for field, messages in error.message_dict.items():
                for message in messages:
                    self.add_error(field if field in self.fields else None, message)
        else:
            for message in error.messages:
                self.add_error(None, message)


def posted_rows(data, prefix, names, filled):
    """Rows added in the browser, sent as lists. A row whose `filled` fields are all blank is skipped.

    Example: action_title=["Send data", ""], action_owner=["5", "5"] -> [{"title": "Send data", "owner": "5"}]
    """
    columns = [data.getlist(f"{prefix}_{name}") for name in names]
    rows = [dict(zip(names, values)) for values in zip(*columns)]
    return [row for row in rows if any(row[name].strip() for name in filled)]


class NewTaskParts:
    """The Actions and Files & links tabs of the New task form. The service checks the rules;
    this only turns the posted text into people and dates."""

    TABS = ("actions", "links", "files")

    def __init__(self, data=None, files=None, *, company):
        self.company = company
        self.action_rows = posted_rows(data, "action", ("title", "owner", "due_date"), ("title",)) if data else []
        self.link_rows = posted_rows(data, "link", ("label", "url"), ("label", "url")) if data else []
        self.files = files.getlist("files") if files else []
        self.errors = {}
        self.actions, self.links = [], [dict(row) for row in self.link_rows]

    def is_valid(self, due_date=None):
        """Check every row now, so all tabs show their errors together. `due_date`: the task's, if valid."""
        people = {str(person.pk): person for person in services.people_of(self.company)}
        problems = []
        for number, row in enumerate(self.action_rows, 1):
            owner = people.get(row["owner"])
            try:
                due_date = date.fromisoformat(row["due_date"])
            except ValueError:
                due_date = None
            if owner is None:
                problems.append(f"Action {number}: pick who does it.")
            if due_date is None:
                problems.append(f"Action {number}: pick a due date.")
            if owner and due_date:
                self.actions.append({"title": row["title"], "owner": owner, "due_date": due_date})
        if problems:
            self.errors["actions"] = problems
        found = services.task_part_problems(self.company, due_date, self.actions, self.links, self.files)
        for tab, messages in found.items():
            self.errors.setdefault(tab, []).extend(messages)
        return not self.errors

    def take_service_errors(self, error):
        """Keep this part's messages (actions, links, files); return the rest for the main form, or None."""
        if not hasattr(error, "error_dict"):
            return error
        rest = {}
        for field, messages in error.message_dict.items():
            if field in self.TABS:
                self.errors.setdefault(field, []).extend(messages)
            else:
                rest[field] = messages
        return ValidationError(rest) if rest else None


def task_initial(task):
    return {
        "title": task.title, "owner": task.owner_id, "due_date": task.due_date, "category": task.category_id,
        "priority": task.priority, "reviewer": task.reviewer_id, "status": task.status,
        "collaborators": list(task.collaborators.values_list("pk", flat=True)), "description": task.description,
    }


NUMBER = "input input-sm w-full"
DAY_CHOICES = [("", "Pick a day"), *[(day, str(day)) for day in range(1, 31)], (LAST_DAY, "Last day of month")]
MONTH_CHOICES = [("", "Pick a month"), *[(number, calendar.month_name[number]) for number in range(1, 13)]]
WEEKDAY_CHOICES = [("", "Pick a weekday"), *enumerate(WEEKDAYS)]


def optional_number(choices, **kwargs):
    return forms.TypedChoiceField(
        choices=choices, coerce=int, empty_value=None, required=False,
        widget=forms.Select(attrs={"class": SELECT}), **kwargs,
    )


class RuleForm(forms.Form):
    """Fields of a repeating rule. There is no due date here: the rule says when each task is due."""

    title = forms.CharField(max_length=200, widget=forms.TextInput(attrs={"class": INPUT}),
                            help_text='Without the month or year: "GSTR1", not "GSTR1 - Oct 2026".')
    owner = PersonField(queryset=None, widget=forms.Select(attrs={"class": SELECT}),
                        help_text="Every task of this rule is given to this person.")
    reviewer = PersonField(queryset=None, required=False, empty_label="None",
                           widget=forms.Select(attrs={"class": SELECT}))
    category = forms.ModelChoiceField(queryset=None, required=False, widget=forms.Select(attrs={"class": SELECT}))
    priority = forms.ChoiceField(choices=Task.Priority.choices, initial=Task.Priority.MEDIUM,
                                 widget=forms.Select(attrs={"class": SELECT}))
    frequency = forms.ChoiceField(
        label="Repeats", choices=RecurringTask.Frequency.choices, initial=RecurringTask.Frequency.MONTHLY,
        widget=forms.Select(attrs={"class": SELECT, "x-model": "frequency"}),
    )
    repeat_every = forms.IntegerField(
        label="Every", min_value=1, max_value=60, initial=1, widget=forms.NumberInput(attrs={"class": NUMBER}),
        help_text="1 = every month, 3 = every 3 months (a quarter).",
    )
    weekday = optional_number(WEEKDAY_CHOICES, label="Due on")
    due_day = optional_number(DAY_CHOICES, label="Due day")
    due_month = optional_number(MONTH_CHOICES, label="Due month")
    due_in_next_period = forms.BooleanField(
        label="Due in the next period", required=False, widget=forms.CheckboxInput(attrs={"class": "checkbox checkbox-sm"}),
        help_text="Example: October's work, due on a day in November.",
    )
    off_day_rule = forms.ChoiceField(
        label="If due on an off day", choices=RecurringTask.OffDayRule.choices,
        widget=forms.Select(attrs={"class": SELECT}), help_text="Off days: Sundays, the off Saturdays and holidays.",
    )
    create_days_before = forms.IntegerField(
        label="Show the task (days before due)", min_value=0, max_value=90, initial=7,
        widget=forms.NumberInput(attrs={"class": NUMBER}),
        help_text="7 = the task appears in the lists 7 days before its due date.",
    )
    start_date = forms.DateField(label="Start from", widget=date_input())
    end_date = forms.DateField(label="Stop after (optional)", required=False, widget=date_input())
    collaborators = PeopleField(queryset=None, required=False, widget=forms.CheckboxSelectMultiple,
                                help_text="Copied to every task of this rule.")
    description = forms.CharField(required=False, widget=forms.Textarea(attrs={"class": TEXTAREA, "rows": 3}))

    add_service_errors = TaskForm.add_service_errors

    def __init__(self, *args, company, read_only=False, **kwargs):
        super().__init__(*args, **kwargs)
        people = services.people_of(company)
        for name in ("owner", "reviewer", "collaborators"):
            self.fields[name].queryset = people
        self.fields["category"].queryset = services.categories_of(company)
        if read_only:
            for field in self.fields.values():
                field.disabled = True


def rule_initial(rule):
    initial = {name: getattr(rule, name) for name in services.RULE_FIELDS if name not in ("owner", "reviewer", "category")}
    initial.update(
        owner=rule.owner_id, reviewer=rule.reviewer_id, category=rule.category_id,
        collaborators=list(rule.collaborators.values_list("pk", flat=True)),
    )
    return initial


class RuleActionForm(forms.Form):
    title = forms.CharField(max_length=200, widget=forms.TextInput(attrs={"class": INPUT, "placeholder": "New action"}))
    owner = PersonField(queryset=None, widget=forms.Select(attrs={"class": SELECT}))
    days_before_due = forms.IntegerField(
        min_value=0, max_value=365, initial=0, widget=forms.NumberInput(attrs={"class": NUMBER, "title": "Days before the task's due date. 0 = on the due date."}),
    )

    def __init__(self, *args, rule, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["owner"].queryset = services.people_of(rule.company)
        self.fields["owner"].initial = rule.owner_id


class HolidayForm(forms.Form):
    company = forms.ModelChoiceField(queryset=None, widget=forms.Select(attrs={"class": SELECT}))
    date = forms.DateField(widget=date_input())
    name = forms.CharField(max_length=100, widget=forms.TextInput(attrs={"class": INPUT, "placeholder": "e.g. Diwali"}))

    def __init__(self, *args, companies, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["company"].queryset = Company.objects.filter(pk__in=[company.pk for company in companies])
        if len(companies) == 1:
            self.fields["company"].initial = companies[0].pk


class ActionForm(forms.Form):
    title = forms.CharField(max_length=200, widget=forms.TextInput(attrs={"class": INPUT, "placeholder": "New action"}))
    owner = PersonField(queryset=None, widget=forms.Select(attrs={"class": SELECT}))
    due_date = forms.DateField(widget=date_input())

    def __init__(self, *args, task, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["owner"].queryset = services.people_of(task.company)
        self.fields["owner"].initial = task.owner_id
        self.fields["due_date"].initial = task.due_date
