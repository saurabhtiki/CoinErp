from django import forms

from . import services
from .models import Task

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


def task_initial(task):
    return {
        "title": task.title, "owner": task.owner_id, "due_date": task.due_date, "category": task.category_id,
        "priority": task.priority, "reviewer": task.reviewer_id, "status": task.status,
        "collaborators": list(task.collaborators.values_list("pk", flat=True)), "description": task.description,
    }


class ActionForm(forms.Form):
    title = forms.CharField(max_length=200, widget=forms.TextInput(attrs={"class": INPUT, "placeholder": "New action"}))
    owner = PersonField(queryset=None, widget=forms.Select(attrs={"class": SELECT}))
    due_date = forms.DateField(widget=date_input())

    def __init__(self, *args, task, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["owner"].queryset = services.people_of(task.company)
        self.fields["owner"].initial = task.owner_id
        self.fields["due_date"].initial = task.due_date
