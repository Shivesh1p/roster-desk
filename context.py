"""Read-only lookups shared by the scheduler and the validator."""
from collections import defaultdict
from typing import List, Optional

from calendar_rules import holiday_dates, is_open, required_staff
from models import AssignmentRole, CalendarType, Dataset, LeaveType, Status

# Any of these means "not working this day".
REST = {Status.WEEKLY_OFF, Status.LEAVE, Status.COMP_OFF, Status.HOLIDAY}

STATUS_LABEL = {
    Status.WORK: "working",
    Status.WEEKLY_OFF: "on weekly off",
    Status.LEAVE: "on leave",
    Status.COMP_OFF: "on comp-off",
    Status.HOLIDAY: "on a public holiday",
}


class Context:
    def __init__(self, ds: Dataset):
        self.ds = ds
        self.emp = {e.id: e for e in ds.employees}
        self.proc = {p.id: p for p in ds.processes}
        self.brand = {b.id: b for b in ds.brands}
        self.pod = {p.id: p for p in ds.pods}
        self.hol = holiday_dates(ds.holidays)

        self.primaries = defaultdict(list)   # process_id -> [employee ids]
        self.backups = defaultdict(list)     # process_id -> [employee ids]
        self.emp_procs = defaultdict(list)   # employee_id -> [process ids they own]
        for a in ds.assignments:
            if a.role == AssignmentRole.PRIMARY:
                self.primaries[a.process_id].append(a.employee_id)
                self.emp_procs[a.employee_id].append(a.process_id)
            else:
                self.backups[a.process_id].append(a.employee_id)

        self.leaves = defaultdict(list)
        for lv in ds.leaves:
            self.leaves[lv.employee_id].append(lv)

        self.brand_procs = defaultdict(list)
        self.pod_procs = defaultdict(list)
        for pr in ds.processes:
            self.brand_procs[pr.brand_id].append(pr.id)
            self.pod_procs[self.brand[pr.brand_id].pod_id].append(pr.id)

    # --- calendar helpers ---------------------------------------------
    def is_open(self, pid: int, d) -> bool:
        return is_open(self.proc[pid], d, self.hol)

    def required(self, pid: int, d) -> int:
        return required_staff(self.proc[pid], d, self.hol)

    def label(self, pid: int) -> str:
        p = self.proc[pid]
        return f"{self.brand[p.brand_id].name} / {p.name}"

    # --- what an employee's day looks like before any planning ----------
    def relevant(self, emp_id: int) -> List[int]:
        """Processes that decide whether this person has work on a day.
        Owners: the processes they own. Pod leads (own nothing): the whole pod."""
        procs = self.emp_procs.get(emp_id)
        if procs:
            return procs
        return self.pod_procs[self.emp[emp_id].pod_id]

    def natural_sunday_off(self, emp_id: int) -> bool:
        """True if every relevant process is closed on Sundays (Mon-Sat calendars)."""
        rel = self.relevant(emp_id)
        return bool(rel) and all(
            self.proc[p].calendar == CalendarType.NO_SUN_HOLIDAYS for p in rel)

    def fixed_status(self, emp_id: int, d) -> Optional[Status]:
        """Status forced by calendars and approved leave. None = free to plan."""
        rel = self.relevant(emp_id)
        if rel and not any(self.is_open(p, d) for p in rel):
            return Status.HOLIDAY if d in self.hol else Status.WEEKLY_OFF
        for lv in self.leaves.get(emp_id, []):
            if lv.covers(d):
                return Status.COMP_OFF if lv.type == LeaveType.COMP_OFF else Status.LEAVE
        return None
