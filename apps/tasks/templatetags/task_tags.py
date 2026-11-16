from django import template

from apps.tasks import services

register = template.Library()


@register.filter
def can_finish(task, user):
    """Show the Done button on a list row? Example: {% if row|can_finish:request.user %}."""
    return services.can_finish_row(user, task)
