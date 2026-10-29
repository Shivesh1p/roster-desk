"""Operating-calendar rules.

Key idea: a process's OPERATING calendar (when coverage is required) is kept
separate from an employee's WORKING schedule (when that person actually works).
"""
from datetime import date, timedelta
from typing import Iterable, List, Set

from models import CalendarType, Process

SUNDAY = 6


def holiday_dates(holidays) -> Set[date]:
    return {h.day for h in holidays}


def is_open(process: Process, d: date, holidays: Set[date]) -> bool:
    """Does this process need coverage on day d?"""
    if process.calendar == CalendarType.ALL_365:
        return True
    if process.calendar == CalendarType.NO_HOLIDAYS:
        return d not in holidays
    if process.calendar == CalendarType.NO_SUN_HOLIDAYS:
        return d.weekday() != SUNDAY and d not in holidays
    raise ValueError(f"Unknown calendar type: {process.calendar}")


def required_staff(process: Process, d: date, holidays: Set[date]) -> int:
    """How many people must be working this process on day d (0 if closed)."""
    if not is_open(process, d, holidays):
        return 0
    return process.min_staff_overrides.get(d.weekday(), process.min_staff)


def month_days(year: int, month: int) -> List[date]:
    d = date(year, month, 1)
    days = []
    while d.month == month:
        days.append(d)
        d += timedelta(days=1)
    return days
