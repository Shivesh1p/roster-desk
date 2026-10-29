"""Core data model for the roster system.

Everything the operations manager configures lives in these plain objects,
so new brands / processes / rules need data changes, not code changes.
"""
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Dict, Optional


class CalendarType(str, Enum):
    """A process's operating calendar = the days coverage is REQUIRED."""
    ALL_365 = "365"                    # every day incl. Sundays and public holidays
    NO_HOLIDAYS = "NO_HOLIDAYS"        # every day except public holidays
    NO_SUN_HOLIDAYS = "NO_SUN_HOLIDAYS"  # Mon-Sat, minus public holidays


class AssignmentRole(str, Enum):
    PRIMARY = "PRIMARY"   # regular owner of the process
    BACKUP = "BACKUP"     # can be pulled in to cover a gap


class LeaveType(str, Enum):
    PLANNED = "PLANNED"
    COMP_OFF = "COMP_OFF"


class Status(str, Enum):
    """What one employee is doing on one day (a RosterEntry value)."""
    WORK = "WORK"
    WEEKLY_OFF = "WEEKLY_OFF"
    LEAVE = "LEAVE"
    COMP_OFF = "COMP_OFF"
    HOLIDAY = "HOLIDAY"


@dataclass
class Employee:
    id: int
    name: str
    pod_id: int
    is_pod_lead: bool = False
    preferred_off_weekday: Optional[int] = None  # 0=Mon ... 6=Sun (a PREFERENCE only)
    max_consecutive_days: int = 6                # a MANDATORY limit


@dataclass
class Pod:
    id: int
    name: str
    lead_id: int


@dataclass
class Brand:
    id: int
    name: str
    pod_id: int


@dataclass
class Process:
    id: int
    brand_id: int
    name: str                      # CS, ACC, RET, NDR ...
    calendar: CalendarType
    min_staff: int = 1
    # weekday (0=Mon..6=Sun) -> minimum staff on that weekday, overrides min_staff
    min_staff_overrides: Dict[int, int] = field(default_factory=dict)


@dataclass
class Assignment:
    employee_id: int
    process_id: int
    role: AssignmentRole = AssignmentRole.PRIMARY


@dataclass
class Holiday:
    day: date
    name: str


@dataclass
class Leave:
    employee_id: int
    start: date
    end: date                      # inclusive
    type: LeaveType = LeaveType.PLANNED
    note: str = ""

    def covers(self, d: date) -> bool:
        return self.start <= d <= self.end


@dataclass
class Dataset:
    """Everything the scheduler needs, in one container."""
    pods: list
    employees: list
    brands: list
    processes: list
    assignments: list
    holidays: list
    leaves: list
