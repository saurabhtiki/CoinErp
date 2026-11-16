from django import template

from apps.tasks import schedule, services

register = template.Library()


@register.filter
def can_finish(task, user):
    """Show the Done button on a list row? Example: {% if row|can_finish:request.user %}."""
    return services.can_finish_row(user, task)


@register.filter
def can_change(record, user):
    """May the user change this list row (one they may already see)? Example: {% if row|can_change:request.user %}."""
    return services.can_manage(user, record, visible=True)


@register.filter
def repeats(rule):
    """A rule's timing in words. Example: "Every month on day 11 of the next month"."""
    return schedule.describe(rule)


@register.simple_tag(takes_context=True)
def next_due(context, rule):
    """The rule's next due date for a list row. The company's off days are read once per page."""
    if rule.is_paused:
        return "paused"
    cache = context["request"].__dict__.setdefault("_task_off_days", {})
    if rule.company_id not in cache:
        cache[rule.company_id] = services.off_days_of(rule.company)
    found = services.upcoming(rule, cache[rule.company_id], count=1)
    return f"{found[0].due:%a %d %b %Y}" if found else "ended"
