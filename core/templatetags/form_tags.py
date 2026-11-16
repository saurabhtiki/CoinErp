from django import template

register = template.Library()


@register.filter
def add_class(field, css_classes):
    """Render a form field with DaisyUI classes, e.g. {{ form.email|add_class:"input w-full" }}."""
    return field.as_widget(attrs={"class": css_classes})
