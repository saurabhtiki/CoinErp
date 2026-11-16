from django import template

register = template.Library()


@register.filter
def cell(row, column):
    """Value of one table cell, e.g. {{ row|cell:column }}. Uses the column's choice label if it has one."""
    value = getattr(row, column.name, "")
    if column.choices and value in column.choices:
        return column.choices[value]
    return "" if value is None else value
