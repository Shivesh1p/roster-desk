"""Change handling: apply a change to an EXISTING roster without rebuilding it.

The manager never has to regenerate the month after a leave request or a manual edit.
Only the people and days touched by the change are re-planned; everyone else's roster
stays exactly as published. The result is a PREVIEW (nothing is saved until the caller
decides to keep `impact.roster` / `impact.ds`).

    evaluate_changes()  -> the one engine (leave, cancelled leave, manual edit)
    evaluate_leave()    -> convenience wrapper for a new leave / comp-off
    evaluate_cancel()   -> convenience wrapper for cancelling an approved leave
    evaluate_edit()     -> convenience wrapper for a manual cell edit
"""
import copy
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

from calendar_rules import month_days
from context import REST
from models import Dataset, Leave, LeaveType, Status
from scheduler import Planner, Roster
from validator import MANDATORY, fmt, validate

# (employee_id, day, new_status). new_status None = "restore the normal status".
Change = Tuple[int, date, Optional[Status]]


@dataclass
class Impact:
    title: str
    summary: str = ""
    items: List[dict] = field(default_factory=list)       # one per affected process-day
    notes: List[str] = field(default_factory=list)        # e.g. "already on weekly off"
    introduced: List[dict] = field(default_factory=list)  # NEW mandatory problems
    cleared: List[dict] = field(default_factory=list)     # problems the change removed
    ds: Optional[Dataset] = None                          # dataset if the change is kept
    roster: Optional[Roster] = None                       # roster if the change is kept

    @property
    def needs_decision(self) -> bool:
        return any(i["status"] == "UNCOVERED" for i in self.items)


def conflict_dict(x) -> dict:
    return {"severity": x.severity, "code": x.code, "message": x.message,
            "day": x.day.isoformat() if x.day else None,
            "brand_id": x.brand_id, "process_id": x.process_id,
            "employee_ids": list(x.employee_ids)}


def impact_dict(imp: Impact) -> dict:
    return {"title": imp.title, "summary": imp.summary, "items": imp.items,
            "notes": imp.notes, "introduced": imp.introduced, "cleared": imp.cleared,
            "needs_decision": imp.needs_decision}


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------
def _owned_open_brands(c, emp_id, d):
    return {c.proc[p].brand_id for p in c.emp_procs.get(emp_id, []) if c.is_open(p, d)}


def _why_blocked(pl: Planner, e, pid, d) -> str:
    """Plain-language reason a free-looking person cannot take this cover."""
    c = pl.c
    brand = c.proc[pid].brand_id
    other = pl.covering_brands(e.id, d) - {brand}
    if other:
        return f"{e.name} is already covering {c.brand[next(iter(other))].name}"
    for q in c.emp_procs.get(e.id, []):
        if c.is_open(q, d) and pl.have(q, d, exclude=e.id) < c.required(q, d):
            return f"{e.name} is needed on their own {c.label(q)}"
    return f"{e.name} is not eligible"


def resolution_options(pl: Planner, pid: int, d: date, limit: int = 5) -> List[dict]:
    """Ranked ideas for a gap the generator could not close on its own.

    Rank: assigned backup > same-pod colleague; pod lead last. A person who is on a
    plain weekly off can be ASKED to work (comp-off in lieu) - that is a human decision,
    so it is only suggested, never applied automatically.
    """
    c = pl.c
    brand = c.proc[pid].brand_id
    pod = c.brand[brand].pod_id
    ranked = []
    for e in c.ds.employees:
        if e.id in c.primaries[pid]:
            continue
        assigned = e.id in c.backups[pid]
        if not (assigned or e.pod_id == pod):
            continue
        s = pl.st(e.id, d)
        key = (e.is_pod_lead, not assigned, e.id)
        if s == Status.WEEKLY_OFF:
            ranked.append((0, key, {
                "employee_id": e.id, "name": e.name, "kind": "ASK_TO_WORK_OFF_DAY",
                "text": (f"Ask {e.name} ({'assigned backup' if assigned else 'same pod'}) "
                         f"to work their weekly off on {fmt(d)} and give a comp-off later.")}))
        elif s == Status.WORK:
            ranked.append((1, key, {
                "employee_id": e.id, "name": e.name, "kind": "BLOCKED",
                "text": _why_blocked(pl, e, pid, d) + "."}))
    ranked.sort(key=lambda t: (t[0], t[1]))
    return [r[2] for r in ranked[:limit]]


def _trim_extra_cover(pl: Planner, pid: int, d: date):
    """After someone is back at work, drop cover that is no longer needed."""
    lst = pl.r.covers.get((pid, d), [])
    while lst and pl.working_primaries(pid, d) >= pl.c.required(pid, d):
        lst.pop()
    if not lst:
        pl.r.covers.pop((pid, d), None)


# ----------------------------------------------------------------------
# the engine
# ----------------------------------------------------------------------
def evaluate_changes(ds: Dataset, roster: Roster, changes: List[Change], title: str,
                     add_leaves: List[Leave] = (), remove_leaves: List[Leave] = ()) -> Impact:
    new_ds = Dataset(pods=ds.pods, employees=ds.employees, brands=ds.brands,
                     processes=ds.processes, assignments=ds.assignments,
                     holidays=ds.holidays,
                     leaves=[lv for lv in ds.leaves if lv not in remove_leaves]
                            + list(add_leaves))
    pl = Planner(new_ds, roster.year, roster.month)
    pl.r = copy.deepcopy(roster)
    c = pl.c
    in_month = set(month_days(roster.year, roster.month))
    original_covers = {k: list(v) for k, v in roster.covers.items()}
    imp = Impact(title=title, ds=new_ds, roster=pl.r)

    focus = set()          # (process_id, day) pairs worth reporting on
    recover = set()        # (brand_id, day) pairs to re-plan
    for emp_id, d, new in changes:
        if d not in in_month:
            continue
        e = c.emp[emp_id]
        old = pl.r.status[(emp_id, d)]
        if new is None:                                    # restore normal status
            new = c.fixed_status(emp_id, d)
            if new is None:
                new = (Status.WEEKLY_OFF if pl.r.off_weekday.get(emp_id) == d.weekday()
                       else Status.WORK)
        if old == new:
            continue
        if old in REST and new in REST:
            if old == Status.WEEKLY_OFF and new in (Status.LEAVE, Status.COMP_OFF):
                imp.notes.append(f"{e.name} was already on weekly off on {fmt(d)}; "
                                 f"the {new.value.lower().replace('_', '-')} costs nothing there.")
                continue                                   # keep the weekly off as is
            if old == Status.HOLIDAY:
                imp.notes.append(f"{fmt(d)} is a public holiday for {e.name}; no change.")
                continue
            pl.r.status[(emp_id, d)] = new
            continue
        if new in REST:                                    # WORK -> off: gap risk
            displaced = [pid for (pid, dd), lst in pl.r.covers.items()
                         if dd == d and emp_id in lst]
            for pid in displaced:
                pl.r.covers[(pid, d)].remove(emp_id)
                if not pl.r.covers[(pid, d)]:
                    pl.r.covers.pop((pid, d))
                focus.add((pid, d))
                recover.add((c.proc[pid].brand_id, d))
            pl.r.status[(emp_id, d)] = new
            for pid in c.emp_procs.get(emp_id, []):
                if c.is_open(pid, d):
                    focus.add((pid, d))
            for b in _owned_open_brands(c, emp_id, d):
                recover.add((b, d))
        else:                                              # off -> WORK: tidy cover
            pl.r.status[(emp_id, d)] = new
            for pid in c.emp_procs.get(emp_id, []):
                if c.is_open(pid, d):
                    _trim_extra_cover(pl, pid, d)

    for b, d in sorted(recover, key=lambda t: (t[1], t[0])):
        pl.cover_brand(b, d)

    # ---- describe what happened, process-day by process-day --------------
    covered = uncovered = still_ok = 0
    for pid, d in sorted(focus, key=lambda t: (t[1], t[0])):
        need = c.required(pid, d)
        if need == 0:
            continue
        before = original_covers.get((pid, d), [])
        after = pl.r.covers.get((pid, d), [])
        added = [x for x in after if x not in before]
        working = [c.emp[x].name for x in c.primaries[pid]
                   if pl.st(x, d) not in REST and not (pl.covering_brands(x, d)
                                                       - {c.proc[pid].brand_id})]
        have = len(working) + len(after)
        item = {"day": d.isoformat(), "day_label": fmt(d), "process_id": pid,
                "label": c.label(pid), "need": need, "have": have,
                "working": working, "cover": [c.emp[x].name for x in after],
                "added_cover": [c.emp[x].name for x in added], "options": []}
        if have >= need and added:
            item["status"] = "COVERED_BY_BACKUP"
            item["message"] = (f"{c.label(pid)} on {fmt(d)}: covered by "
                               f"{', '.join(item['added_cover'])}.")
            covered += 1
        elif have >= need:
            item["status"] = "STILL_COVERED"
            item["message"] = (f"{c.label(pid)} on {fmt(d)}: remaining staff "
                               f"({', '.join(working) or 'cover'}) still meet the "
                               f"requirement of {need}.")
            still_ok += 1
        else:
            item["status"] = "UNCOVERED"
            item["options"] = resolution_options(pl, pid, d)
            item["message"] = (f"{c.label(pid)} on {fmt(d)}: needs {need}, only {have} "
                               f"available. Your decision is needed.")
            uncovered += 1
        imp.items.append(item)

    # ---- compare validator results before / after ------------------------
    key = lambda x: (x.code, x.message)
    old_set = {key(x): x for x in validate(ds, roster)}
    new_all = validate(new_ds, pl.r)
    new_set = {key(x): x for x in new_all}
    imp.introduced = [conflict_dict(x) for k, x in new_set.items()
                      if k not in old_set and x.severity == MANDATORY]
    imp.cleared = [conflict_dict(x) for k, x in old_set.items()
                   if k not in new_set and x.severity == MANDATORY]

    parts = [f"{len(imp.items)} process-day(s) affected"]
    if covered:
        parts.append(f"{covered} covered by a backup")
    if still_ok:
        parts.append(f"{still_ok} still fine with remaining staff")
    if uncovered:
        parts.append(f"{uncovered} need your decision")
    if imp.introduced:
        parts.append(f"{len(imp.introduced)} new mandatory issue(s)")
    imp.summary = "; ".join(parts) + "."
    if not imp.items and not imp.notes:
        imp.summary = "No process is affected by this change."
    return imp


# ----------------------------------------------------------------------
# convenience wrappers
# ----------------------------------------------------------------------
def _days(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def evaluate_leave(ds, roster, emp_id, start, end, ltype=LeaveType.PLANNED, note="") -> Impact:
    e = next(x for x in ds.employees if x.id == emp_id)
    status = Status.COMP_OFF if ltype == LeaveType.COMP_OFF else Status.LEAVE
    changes = [(emp_id, d, status) for d in _days(start, end)]
    label = "comp-off" if ltype == LeaveType.COMP_OFF else "leave"
    title = f"{e.name} on {label}: {fmt(start)} to {fmt(end)}"
    return evaluate_changes(ds, roster, changes, title,
                            add_leaves=[Leave(emp_id, start, end, ltype, note)])


def evaluate_cancel(ds, roster, leave: Leave) -> Impact:
    e = next(x for x in ds.employees if x.id == leave.employee_id)
    changes = [(leave.employee_id, d, None) for d in _days(leave.start, leave.end)]
    title = f"Cancel {e.name}'s leave: {fmt(leave.start)} to {fmt(leave.end)}"
    return evaluate_changes(ds, roster, changes, title, remove_leaves=[leave])


def evaluate_edit(ds, roster, emp_id, day, new_status: Status) -> Impact:
    e = next(x for x in ds.employees if x.id == emp_id)
    title = f"Manual edit: {e.name} -> {new_status.value.replace('_', ' ').title()} on {fmt(day)}"
    return evaluate_changes(ds, roster, [(emp_id, day, new_status)], title)
