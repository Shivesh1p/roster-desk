"""HTTP layer. Thin on purpose: all the scheduling logic lives in scheduler.py,
validator.py and changes.py, so it can be tested without a web server.

Run locally:   uvicorn app:app --reload        then open http://127.0.0.1:8000
State is kept in memory and seeded from seed_data.py (see README: a real database is
the first thing to add for multi-user use). Everything the manager can configure -
pods, brands, processes, calendars, minimum staffing, assignments, holidays, leaves -
is plain data edited through the endpoints below, never through code changes.
"""
import csv
import io
from datetime import date
from pathlib import Path
from typing import Dict, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from changes import (conflict_dict, evaluate_cancel, evaluate_edit, evaluate_leave,
                     impact_dict)
from context import Context, REST
from models import (Assignment, AssignmentRole, Brand, CalendarType, Employee, Holiday,
                    LeaveType, Pod, Process, Status)
from scheduler import Planner, generate_roster
from seed_data import build_dataset
from validator import validate

app = FastAPI(title="Smart Roster Management System")
STATIC = Path(__file__).parent / "static"
CODE = {Status.WORK: "W", Status.WEEKLY_OFF: "O", Status.LEAVE: "L",
        Status.COMP_OFF: "C", Status.HOLIDAY: "H"}


class State:
    def __init__(self):
        self.reset()

    def reset(self):
        self.ds = build_dataset()
        self.rosters = {}                      # (year, month) -> Roster

    def roster(self, y, m):
        if (y, m) not in self.rosters:
            self.rosters[(y, m)] = generate_roster(self.ds, y, m)
        return self.rosters[(y, m)]

    def structure_changed(self):
        """Setup data changed (people, brands, rules): rosters are rebuilt on demand."""
        self.rosters.clear()


STATE = State()


def _check_month(y: int, m: int):
    if not (2000 <= y <= 2100 and 1 <= m <= 12):
        raise HTTPException(400, "Invalid year/month")


def _emp(emp_id: int):
    for e in STATE.ds.employees:
        if e.id == emp_id:
            return e
    raise HTTPException(404, f"Employee {emp_id} not found")


def _next_id(items) -> int:
    return max((x.id for x in items), default=0) + 1


# ----------------------------------------------------------------------
# read: the whole picture for one month
# ----------------------------------------------------------------------
@app.get("/api/state")
def get_state(year: int = Query(2026), month: int = Query(11)):
    _check_month(year, month)
    ds = STATE.ds
    r = STATE.roster(year, month)
    c = Context(ds)
    days = r.days()
    pl = Planner(ds, year, month)
    pl.r = r

    status = {e.id: "".join(CODE[r.status[(e.id, d)]] for d in days) for e in ds.employees}
    covers_by_emp: Dict[int, Dict[int, list]] = {}
    for (pid, d), lst in r.covers.items():
        for e in lst:
            covers_by_emp.setdefault(e, {}).setdefault(days.index(d), []).append(pid)

    coverage, workers = {}, {}
    for p in ds.processes:
        row, wrow = [], []
        for d in days:
            need = c.required(p.id, d)
            who = [e for e in c.primaries[p.id]
                   if r.status[(e, d)] not in REST
                   and not (pl.covering_brands(e, d) - {p.brand_id})]
            who += list(r.covers.get((p.id, d), []))
            row.append([need, len(who)])
            wrow.append(who)
        coverage[p.id] = row
        workers[p.id] = wrow

    return {
        "year": year, "month": month,
        "days": [{"date": d.isoformat(), "day": d.day, "dow": d.weekday(),
                  "holiday": next((h.name for h in ds.holidays if h.day == d), None)}
                 for d in days],
        "pods": [{"id": p.id, "name": p.name, "lead_id": p.lead_id} for p in ds.pods],
        "employees": [{"id": e.id, "name": e.name, "pod_id": e.pod_id,
                       "is_lead": e.is_pod_lead, "pref": e.preferred_off_weekday,
                       "max_consecutive": e.max_consecutive_days,
                       "off_weekday": r.off_weekday.get(e.id)} for e in ds.employees],
        "brands": [{"id": b.id, "name": b.name, "pod_id": b.pod_id} for b in ds.brands],
        "processes": [{"id": p.id, "brand_id": p.brand_id, "name": p.name,
                       "calendar": p.calendar.value, "min_staff": p.min_staff,
                       "overrides": {str(k): v for k, v in p.min_staff_overrides.items()},
                       "owners": c.primaries[p.id], "backups": c.backups[p.id]}
                      for p in ds.processes],
        "holidays": [{"day": h.day.isoformat(), "name": h.name} for h in ds.holidays],
        "leaves": [{"index": i, "employee_id": lv.employee_id, "start": lv.start.isoformat(),
                    "end": lv.end.isoformat(), "type": lv.type.value, "note": lv.note}
                   for i, lv in enumerate(ds.leaves)],
        "status": status,
        "covers": {str(e): {str(i): pids for i, pids in v.items()}
                   for e, v in covers_by_emp.items()},
        "coverage": {str(k): v for k, v in coverage.items()},
        "workers": {str(k): v for k, v in workers.items()},
        "conflicts": [conflict_dict(x) for x in validate(ds, r)],
    }


# ----------------------------------------------------------------------
# changes: always PREVIEW first, then APPLY
# ----------------------------------------------------------------------
class LeaveReq(BaseModel):
    employee_id: int
    start: date
    end: date
    type: str = "PLANNED"
    note: str = ""
    year: int = 2026
    month: int = 11


class CancelReq(BaseModel):
    leave_index: int
    year: int = 2026
    month: int = 11


class EditReq(BaseModel):
    employee_id: int
    day: date
    status: str                      # WORK or WEEKLY_OFF
    year: int = 2026
    month: int = 11


def _leave_impact(req: LeaveReq):
    _check_month(req.year, req.month)
    _emp(req.employee_id)
    if req.end < req.start:
        raise HTTPException(400, "End date is before start date")
    try:
        ltype = LeaveType(req.type)
    except ValueError:
        raise HTTPException(400, "type must be PLANNED or COMP_OFF")
    return evaluate_leave(STATE.ds, STATE.roster(req.year, req.month), req.employee_id,
                          req.start, req.end, ltype, req.note)


def _cancel_impact(req: CancelReq):
    _check_month(req.year, req.month)
    if not (0 <= req.leave_index < len(STATE.ds.leaves)):
        raise HTTPException(404, "Leave not found")
    return evaluate_cancel(STATE.ds, STATE.roster(req.year, req.month),
                           STATE.ds.leaves[req.leave_index])


def _edit_impact(req: EditReq):
    _check_month(req.year, req.month)
    _emp(req.employee_id)
    r = STATE.roster(req.year, req.month)
    try:
        new = Status(req.status)
    except ValueError:
        raise HTTPException(400, "Unknown status")
    if new not in (Status.WORK, Status.WEEKLY_OFF):
        raise HTTPException(400, "Manual edit supports WORK or WEEKLY_OFF. "
                                 "Use the leave form for leave / comp-off.")
    old = r.status.get((req.employee_id, req.day))
    if old is None:
        raise HTTPException(400, "Date is outside the selected month")
    if old in (Status.LEAVE, Status.COMP_OFF):
        raise HTTPException(400, "That day is approved leave - cancel the leave instead.")
    if old == Status.HOLIDAY:
        raise HTTPException(400, "Public holiday for this person - nothing to edit.")
    return evaluate_edit(STATE.ds, r, req.employee_id, req.day, new)


def _commit(imp, year, month):
    """Keep a previewed change. Other cached months are rebuilt on demand so a leave
    spanning two months is honoured in both."""
    STATE.ds = imp.ds
    STATE.rosters = {(year, month): imp.roster}


@app.post("/api/leave/preview")
def leave_preview(req: LeaveReq):
    return impact_dict(_leave_impact(req))


@app.post("/api/leave/apply")
def leave_apply(req: LeaveReq):
    imp = _leave_impact(req)
    _commit(imp, req.year, req.month)
    return impact_dict(imp)


@app.post("/api/leave/cancel/preview")
def cancel_preview(req: CancelReq):
    return impact_dict(_cancel_impact(req))


@app.post("/api/leave/cancel/apply")
def cancel_apply(req: CancelReq):
    imp = _cancel_impact(req)
    _commit(imp, req.year, req.month)
    return impact_dict(imp)


@app.post("/api/edit/preview")
def edit_preview(req: EditReq):
    return impact_dict(_edit_impact(req))


@app.post("/api/edit/apply")
def edit_apply(req: EditReq):
    imp = _edit_impact(req)
    _commit(imp, req.year, req.month)
    return impact_dict(imp)


@app.post("/api/regenerate")
def regenerate(year: int = Query(2026), month: int = Query(11)):
    """Throw away manual edits for this month and plan it again from scratch."""
    _check_month(year, month)
    STATE.rosters.pop((year, month), None)
    return {"ok": True}


@app.post("/api/reset")
def reset():
    STATE.reset()
    return {"ok": True}


# ----------------------------------------------------------------------
# setup data: no code change needed to add / edit / remove any of this
# ----------------------------------------------------------------------
class PodIn(BaseModel):
    name: str


class EmployeeIn(BaseModel):
    name: str
    pod_id: int
    is_pod_lead: bool = False
    preferred_off_weekday: Optional[int] = None
    max_consecutive_days: int = 6


class BrandIn(BaseModel):
    name: str
    pod_id: int


class ProcessIn(BaseModel):
    brand_id: int
    name: str
    calendar: str = "NO_HOLIDAYS"
    min_staff: int = 1
    min_staff_overrides: Dict[int, int] = {}


class ProcessEdit(BaseModel):
    name: Optional[str] = None
    calendar: Optional[str] = None
    min_staff: Optional[int] = None
    min_staff_overrides: Optional[Dict[int, int]] = None


class AssignmentIn(BaseModel):
    employee_id: int
    process_id: int
    role: str = "PRIMARY"


class HolidayIn(BaseModel):
    day: date
    name: str


def _calendar(v: str) -> CalendarType:
    try:
        return CalendarType(v)
    except ValueError:
        raise HTTPException(400, "calendar must be 365, NO_HOLIDAYS or NO_SUN_HOLIDAYS")


def _need(items, item_id, what):
    for x in items:
        if x.id == item_id:
            return x
    raise HTTPException(404, f"{what} {item_id} not found")


@app.post("/api/pods")
def add_pod(body: PodIn):
    ds = STATE.ds
    pod = Pod(id=_next_id(ds.pods), name=body.name.strip(), lead_id=0)
    ds.pods.append(pod)
    STATE.structure_changed()
    return {"id": pod.id}


@app.post("/api/employees")
def add_employee(body: EmployeeIn):
    ds = STATE.ds
    pod = _need(ds.pods, body.pod_id, "Pod")
    if body.preferred_off_weekday is not None and not 0 <= body.preferred_off_weekday <= 6:
        raise HTTPException(400, "preferred_off_weekday must be 0 (Mon) to 6 (Sun)")
    e = Employee(id=_next_id(ds.employees), name=body.name.strip(), pod_id=body.pod_id,
                 is_pod_lead=body.is_pod_lead, preferred_off_weekday=body.preferred_off_weekday,
                 max_consecutive_days=body.max_consecutive_days)
    ds.employees.append(e)
    if body.is_pod_lead:
        pod.lead_id = e.id
    STATE.structure_changed()
    return {"id": e.id}


@app.delete("/api/employees/{emp_id}")
def delete_employee(emp_id: int):
    ds = STATE.ds
    e = _emp(emp_id)
    if e.is_pod_lead:
        raise HTTPException(400, "Reassign the pod lead before removing this person.")
    ds.employees[:] = [x for x in ds.employees if x.id != emp_id]
    ds.assignments[:] = [a for a in ds.assignments if a.employee_id != emp_id]
    ds.leaves[:] = [lv for lv in ds.leaves if lv.employee_id != emp_id]
    STATE.structure_changed()
    return {"ok": True}


@app.post("/api/brands")
def add_brand(body: BrandIn):
    ds = STATE.ds
    _need(ds.pods, body.pod_id, "Pod")
    b = Brand(id=_next_id(ds.brands), name=body.name.strip(), pod_id=body.pod_id)
    ds.brands.append(b)
    STATE.structure_changed()
    return {"id": b.id}


@app.delete("/api/brands/{brand_id}")
def delete_brand(brand_id: int):
    ds = STATE.ds
    _need(ds.brands, brand_id, "Brand")
    gone = {p.id for p in ds.processes if p.brand_id == brand_id}
    ds.brands[:] = [b for b in ds.brands if b.id != brand_id]
    ds.processes[:] = [p for p in ds.processes if p.brand_id != brand_id]
    ds.assignments[:] = [a for a in ds.assignments if a.process_id not in gone]
    STATE.structure_changed()
    return {"ok": True}


@app.post("/api/processes")
def add_process(body: ProcessIn):
    ds = STATE.ds
    _need(ds.brands, body.brand_id, "Brand")
    if body.min_staff < 1:
        raise HTTPException(400, "min_staff must be at least 1")
    p = Process(id=_next_id(ds.processes), brand_id=body.brand_id, name=body.name.strip(),
                calendar=_calendar(body.calendar), min_staff=body.min_staff,
                min_staff_overrides=dict(body.min_staff_overrides))
    ds.processes.append(p)
    STATE.structure_changed()
    return {"id": p.id}


@app.put("/api/processes/{pid}")
def edit_process(pid: int, body: ProcessEdit):
    p = _need(STATE.ds.processes, pid, "Process")
    if body.name is not None:
        p.name = body.name.strip()
    if body.calendar is not None:
        p.calendar = _calendar(body.calendar)
    if body.min_staff is not None:
        if body.min_staff < 1:
            raise HTTPException(400, "min_staff must be at least 1")
        p.min_staff = body.min_staff
    if body.min_staff_overrides is not None:
        p.min_staff_overrides = {int(k): int(v) for k, v in body.min_staff_overrides.items()}
    STATE.structure_changed()
    return {"ok": True}


@app.delete("/api/processes/{pid}")
def delete_process(pid: int):
    ds = STATE.ds
    _need(ds.processes, pid, "Process")
    ds.processes[:] = [p for p in ds.processes if p.id != pid]
    ds.assignments[:] = [a for a in ds.assignments if a.process_id != pid]
    STATE.structure_changed()
    return {"ok": True}


@app.post("/api/assignments")
def set_assignment(body: AssignmentIn):
    ds = STATE.ds
    _emp(body.employee_id)
    _need(ds.processes, body.process_id, "Process")
    try:
        role = AssignmentRole(body.role)
    except ValueError:
        raise HTTPException(400, "role must be PRIMARY or BACKUP")
    ds.assignments[:] = [a for a in ds.assignments
                         if not (a.employee_id == body.employee_id
                                 and a.process_id == body.process_id)]
    ds.assignments.append(Assignment(body.employee_id, body.process_id, role))
    STATE.structure_changed()
    return {"ok": True}


@app.delete("/api/assignments")
def remove_assignment(employee_id: int, process_id: int):
    ds = STATE.ds
    before = len(ds.assignments)
    ds.assignments[:] = [a for a in ds.assignments
                         if not (a.employee_id == employee_id and a.process_id == process_id)]
    if len(ds.assignments) == before:
        raise HTTPException(404, "Assignment not found")
    STATE.structure_changed()
    return {"ok": True}


@app.post("/api/holidays")
def add_holiday(body: HolidayIn):
    ds = STATE.ds
    if any(h.day == body.day for h in ds.holidays):
        raise HTTPException(400, "A holiday already exists on that date")
    ds.holidays.append(Holiday(body.day, body.name.strip()))
    STATE.structure_changed()
    return {"ok": True}


@app.delete("/api/holidays/{day}")
def remove_holiday(day: date):
    ds = STATE.ds
    before = len(ds.holidays)
    ds.holidays[:] = [h for h in ds.holidays if h.day != day]
    if len(ds.holidays) == before:
        raise HTTPException(404, "Holiday not found")
    STATE.structure_changed()
    return {"ok": True}


# ----------------------------------------------------------------------
# export + pages
# ----------------------------------------------------------------------
@app.get("/api/roster.csv")
def export_csv(year: int = Query(2026), month: int = Query(11)):
    _check_month(year, month)
    ds = STATE.ds
    r = STATE.roster(year, month)
    days = r.days()
    pod = {p.id: p.name for p in ds.pods}
    covering = {(e, d) for (_p, d), lst in r.covers.items() for e in lst}
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Employee", "Pod"] + [f"{d.day} {'MTWTFSS'[d.weekday()]}" for d in days])
    for e in ds.employees:
        w.writerow([e.name, pod.get(e.pod_id, "")] +
                   [CODE[r.status[(e.id, d)]] + ("*" if (e.id, d) in covering else "")
                    for d in days])
    w.writerow([])
    w.writerow(["Legend: W work, O weekly off, L leave, C comp-off, H holiday, "
                "* = also covering another process that day"])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition":
                             f'attachment; filename="roster-{year}-{month:02d}.csv"'})


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")
