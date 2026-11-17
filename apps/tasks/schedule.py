"""Dates of a repeating rule. Plain date maths: nothing here reads the database.

Example: rule "GSTR1", monthly, day 11, due in the next period, started 1 Oct 2026
    -> Period(start=1 Oct 2026, label="Oct 2026", due=11 Nov 2026), then "Nov 2026" due 11 Dec 2026 ...
"""
import calendar
from dataclasses import dataclass
from datetime import date, timedelta

WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
SATURDAY, SUNDAY = 5, 6
LAST_DAY = 31  # "day 31" means the last day of the month (30 Nov, 28 Feb)
MAX_SHIFT = 60  # safety stop when looking for a working day


@dataclass(frozen=True)
class Period:
    start: date  # first day of the period; with the rule it names one task
    label: str  # added to the task title, e.g. "Oct 2026"
    due: date


@dataclass(frozen=True)
class OffDays:
    """The days off of one company: its off Saturdays (e.g. {2, 4}) and its holiday dates."""

    saturdays: frozenset = frozenset({2, 4})
    holidays: frozenset = frozenset()

    def is_off(self, day):
        if day.weekday() == SUNDAY or day in self.holidays:
            return True
        return day.weekday() == SATURDAY and (day.day - 1) // 7 + 1 in self.saturdays


def move_off_day(day, off_day_rule, off_days):
    """Move a due date that falls on an off day. Example: Sun 15 Nov, "previous" -> Fri 13 Nov (14th is a 2nd Saturday)."""
    if off_day_rule == "keep":
        return day
    step = timedelta(days=-1 if off_day_rule == "previous" else 1)
    for _ in range(MAX_SHIFT):
        if not off_days.is_off(day):
            break
        day += step
    return day


def add_months(first_day, months):
    """First day of the month `months` later. Example: add_months(1 Nov 2026, 2) -> 1 Jan 2027."""
    month_index = first_day.year * 12 + first_day.month - 1 + months
    return date(month_index // 12, month_index % 12 + 1, 1)


def _day_in_month(first_day, due_day):
    last = calendar.monthrange(first_day.year, first_day.month)[1]
    return first_day.replace(day=min(due_day or LAST_DAY, last))


def _months_label(first, last):
    if first == last:
        return f"{first:%b %Y}"
    if first.year == last.year:
        return f"{first:%b}-{last:%b %Y}"
    return f"{first:%b %Y}-{last:%b %Y}"


def _raw_periods(rule):
    """Every period from the rule's start date, without off-day handling or an end."""
    every = max(rule.repeat_every or 1, 1)
    start = rule.start_date
    shift = 1 if rule.due_in_next_period else 0
    count = 0
    while True:
        if rule.frequency == "daily":
            day = start + timedelta(days=count * every)
            yield Period(day, f"{day:%d %b %Y}", day)
        elif rule.frequency == "weekly":
            monday = start - timedelta(days=start.weekday()) + timedelta(weeks=count * every)
            due = monday + timedelta(days=rule.weekday or 0, weeks=(every - 1) + shift)
            yield Period(monday, f"Week of {monday:%d %b %Y}", due)
        elif rule.frequency == "monthly":
            first = add_months(start.replace(day=1), count * every)
            last = add_months(first, every - 1)
            yield Period(first, _months_label(first, last), _day_in_month(add_months(last, shift), rule.due_day))
        else:  # yearly
            first = date(start.year + count * every, 1, 1)
            last_year = first.year + every - 1
            label = str(first.year) if every == 1 else f"{first.year}-{last_year}"
            due_month = date(last_year + shift, rule.due_month or 1, 1)
            yield Period(first, label, _day_in_month(due_month, rule.due_day))
        count += 1


def periods(rule, off_days):
    """The rule's periods in date order, from its start date to its end date (or for ever: stop reading when done).

    Due dates on off days are moved as the rule says; a daily rule simply has no task on an off day.
    Periods due before the start date are left out. So are periods due before the day the rule's timing
    was last changed (skip_before): a new timing must not fill the past with tasks.
    """
    first_due = max(rule.start_date, getattr(rule, "skip_before", None) or rule.start_date)
    for period in _raw_periods(rule):
        if rule.frequency == "daily":
            if rule.end_date and period.due > rule.end_date:
                return
            if off_days.is_off(period.due) or period.due < first_due:
                continue
            yield period
            continue
        due = move_off_day(period.due, rule.off_day_rule, off_days)
        if rule.end_date and due > rule.end_date:
            return
        if due >= first_due:
            yield Period(period.start, period.label, due)


def describe(rule):
    """The rule in words. Example: "Every month on day 11 of the next month"."""
    every = rule.repeat_every or 1
    unit = {"daily": "day", "weekly": "week", "monthly": "month", "yearly": "year"}[rule.frequency]
    text = f"Every {unit}" if every == 1 else f"Every {every} {unit}s"
    if rule.frequency == "daily":
        return "Every working day" if every == 1 else text
    if rule.frequency == "weekly":
        text += f" on {WEEKDAYS[rule.weekday or 0]}"
    else:
        day = "the last day" if (rule.due_day or LAST_DAY) >= LAST_DAY else f"day {rule.due_day}"
        month = f" of {calendar.month_abbr[rule.due_month or 1]}" if rule.frequency == "yearly" else ""
        text += f" on {day}{month}"
    if rule.due_in_next_period:
        text += f" of the next {unit}" if every == 1 else " after the period ends"
    return text
