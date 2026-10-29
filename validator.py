"""Independent roster validator.

It does NOT trust the generator: it re-derives coverage from the final statuses and
cover assignments. The same function validates a generated roster, a manually edited
one, or a roster after a change (new leave etc.).

Severity:
  MANDATORY  - breaks a client coverage rule / leave / rest rule. Must be fixed or
               consciously accepted by the manager before publishing.
  PREFERENCE - a soft wish (preferred weekly-off day) was not honoured.
"""
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import List, Optional, Tuple

from context import Context, STATUS_LABEL
from models import CalendarType, Dataset, Status
from scheduler import Roster

MANDATORY = "MANDATORY"
PREFERENCE = "PREFERENCE"
COVER_WARN_RATIO = 0.5   # warn when one person is cover on more than half the days
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
CAL_TEXT = {
    CalendarType.ALL_365: "365-day process",
    CalendarType.NO_HOLIDAYS: "runs every day except public holidays",
    CalendarType.NO_SUN_HOLIDAYS: "runs Mon-Sat except public holidays",
}


@dataclass
class Conflict:
    severity: str
    code: str
    message: str
    day: Optional[date] = None
    brand_id: Optional[int] = None
    process_id: Optional[int] = None
    employee_ids: Tuple[int, ...] = ()


def fmt(d: date) -> str:
    return f"{WEEKDAYS[d.weekday()]} {d.day} {d.strftime('%b')}"


def validate(ds: Dataset, roster: Roster) -> List[Conflict]:
    c = Context(ds)
    st = roster.status
    days = roster.days()
    out: List[Conflict] = []

    covering = defaultdict(set)            # (emp, day) -> brand ids they cover
    for (pid, d), lst in roster.covers.items():
        for e in lst:
            covering[(e, d)].add(c.proc[pid].brand_id)

    def name(e):
        return c.emp[e].name

    def primaries_working(pid, d):
        b = c.proc[pid].brand_id
        return [e for e in c.primaries[pid]
                if st.get((e, d)) == Status.WORK and not (covering.get((e, d), set()) - {b})]

    def valid_covers(pid, d):
        return [e for e in roster.covers.get((pid, d), []) if st.get((e, d)) == Status.WORK]

    def why_unavailable(e, pid, d):
        s = st.get((e, d))
        if s != Status.WORK:
            return f"{name(e)} is {STATUS_LABEL.get(s, str(s))}"
        other = covering.get((e, d), set()) - {c.proc[pid].brand_id}
        if other:
            return f"{name(e)} is already covering {c.brand[next(iter(other))].name}"
        for q in c.emp_procs.get(e, []):
            # would their own process still be covered WITHOUT this person?
            others = [x for x in primaries_working(q, d) if x != e]
            if c.is_open(q, d) and len(others) + len(valid_covers(q, d)) < c.required(q, d):
                return f"{name(e)} is needed on their own {c.label(q)}"
        return f"{name(e)} is free but not assigned to cover"

    # ---- 1. coverage on every open process-day --------------------------
    for d in days:
        for p in ds.processes:
            need = c.required(p.id, d)
            if need == 0:
                continue
            have = len(primaries_working(p.id, d)) + len(valid_covers(p.id, d))
            if have >= need:
                continue
            parts = []
            for e in c.primaries[p.id]:
                s = st.get((e, d))
                busy = covering.get((e, d), set()) - {p.brand_id}
                parts.append(f"{name(e)} is covering {c.brand[next(iter(busy))].name}"
                             if busy else f"{name(e)} is {STATUS_LABEL.get(s, str(s))}")
            owners = "; ".join(parts) if parts else "nobody is assigned"
            bks = c.backups.get(p.id, [])
            backup_txt = ("Backups: " + "; ".join(why_unavailable(e, p.id, d) for e in bks)
                          if bks else "No backup is assigned to this process")
            out.append(Conflict(
                MANDATORY, "COVERAGE_GAP",
                f"{c.label(p.id)} needs {need} on {fmt(d)} ({CAL_TEXT[p.calendar]}) "
                f"but only {have} available. {owners}. {backup_txt}.",
                d, p.brand_id, p.id, tuple(c.primaries[p.id])))

    # ---- 2. cover assignments must be real ------------------------------
    for (e, d), brands in covering.items():
        if len(brands) > 1:
            out.append(Conflict(
                MANDATORY, "DOUBLE_BOOKED",
                f"{name(e)} is assigned to cover {len(brands)} brands on {fmt(d)} "
                f"({', '.join(sorted(c.brand[b].name for b in brands))}).",
                d, employee_ids=(e,)))
        if st.get((e, d)) != Status.WORK:
            out.append(Conflict(
                MANDATORY, "INVALID_COVER",
                f"{name(e)} is assigned as cover on {fmt(d)} but is "
                f"{STATUS_LABEL.get(st.get((e, d)), 'not working')}.", d, employee_ids=(e,)))

    # ---- 3. approved leave must be respected ----------------------------
    for lv in ds.leaves:
        d = lv.start
        while d <= lv.end:
            if d in set(days) and st.get((lv.employee_id, d)) == Status.WORK:
                out.append(Conflict(
                    MANDATORY, "LEAVE_VIOLATED",
                    f"{name(lv.employee_id)} has approved {lv.type.value.lower()} on "
                    f"{fmt(d)} but is rostered to work.", d, employee_ids=(lv.employee_id,)))
            d += timedelta(days=1)

    # ---- 4. rest rules --------------------------------------------------
    for e in ds.employees:
        limit = e.max_consecutive_days
        run, start = 0, None
        for d in days:
            if st.get((e.id, d)) == Status.WORK:
                run += 1
                start = start or d
                if run == limit + 1:
                    out.append(Conflict(
                        MANDATORY, "MAX_CONSECUTIVE",
                        f"{e.name} works more than {limit} days in a row "
                        f"(from {fmt(start)}).", d, employee_ids=(e.id,)))
            else:
                run, start = 0, None
        for d in days:                                    # full Mon-Sun weeks only
            if d.weekday() == 0 and d + timedelta(days=6) in set(days):
                week = [d + timedelta(days=i) for i in range(7)]
                if all(st.get((e.id, x)) == Status.WORK for x in week):
                    out.append(Conflict(
                        MANDATORY, "NO_WEEKLY_OFF",
                        f"{e.name} has no day off in the week of {fmt(d)}.",
                        d, employee_ids=(e.id,)))

    # ---- 5. preferences (soft) ------------------------------------------
    for e in ds.employees:
        if e.preferred_off_weekday is None:
            continue
        offs = Counter(d.weekday() for d in days if st.get((e.id, d)) == Status.WEEKLY_OFF)
        if not offs:
            continue
        actual = offs.most_common(1)[0][0]
        if actual != e.preferred_off_weekday:
            out.append(Conflict(
                PREFERENCE, "PREFERRED_OFF_NOT_MET",
                f"{e.name} prefers {WEEKDAYS[e.preferred_off_weekday]} off but got "
                f"{WEEKDAYS[actual]} (coverage rules came first).", employee_ids=(e.id,)))

    # ---- 6. capacity warning (soft): someone is the safety net too often ----
    cover_days_by_emp = Counter(e for (e, _d) in covering)
    limit_days = max(1, int(len(days) * COVER_WARN_RATIO))
    for e, n in cover_days_by_emp.items():
        if n > limit_days:
            pod_name = c.pod[c.emp[e].pod_id].name
            out.append(Conflict(
                PREFERENCE, "CAPACITY_WARNING",
                f"{name(e)} is pulled in as cover on {n} of {len(days)} days. "
                f"{pod_name} has little spare capacity - consider adding a backup.",
                employee_ids=(e,)))

    order = {MANDATORY: 0, PREFERENCE: 1}
    out.sort(key=lambda x: (order[x.severity], x.day or date.max, x.code))
    return out
