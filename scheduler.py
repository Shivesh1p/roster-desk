"""Monthly roster generation: deterministic greedy + cover assignment.

Phases (same order as the design note):
  1. FIXED      - holidays / closed days / approved leave & comp-offs are placed first.
  2. LEAVE COVER- gaps caused by those fixed days get a backup person if one is free.
  3. WEEKLY OFFS- each person gets ONE fixed weekday off. Riskiest people first
                  (pod leads first, then sole owners of a brand). Every weekday is
                  tried on the real month; the first one that keeps all coverage (using
                  backups where needed) wins. Preference only decides the ORDER of tries,
                  so coverage (mandatory) always beats preference (soft).
  4. FILL       - everything left is a WORK day.

The generator is allowed to FAIL to fully cover something. It never hides that: the
independent validator (validator.py) re-checks the finished roster from scratch.
"""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Tuple

from calendar_rules import month_days
from context import Context, REST
from models import Dataset, Status


@dataclass
class Roster:
    year: int
    month: int
    # (employee_id, day) -> Status
    status: Dict[Tuple[int, date], Status] = field(default_factory=dict)
    # (process_id, day) -> employee ids pulled in as COVER for that process that day
    covers: Dict[Tuple[int, date], List[int]] = field(default_factory=dict)
    # employee_id -> weekday (0=Mon..6=Sun) chosen for the weekly off
    off_weekday: Dict[int, int] = field(default_factory=dict)

    def days(self) -> List[date]:
        return month_days(self.year, self.month)


class Planner:
    EXTRA = 3   # fairness penalty (in cover-days) for a colleague who is not a named backup

    def __init__(self, ds: Dataset, year: int, month: int):
        self.c = Context(ds)
        self.r = Roster(year, month)
        self.days = month_days(year, month)

    # ------------------------------------------------------------------
    # small helpers
    # ------------------------------------------------------------------
    def st(self, e, d):
        return self.r.status.get((e, d))

    def covering_brands(self, e, d):
        """Brands this person is already pulled in to cover on day d."""
        return {self.c.proc[p].brand_id
                for (p, dd), lst in self.r.covers.items() if dd == d and e in lst}

    def cover_days(self, e) -> int:
        return sum(1 for lst in self.r.covers.values() if e in lst)

    def working_primaries(self, pid, d, exclude=None) -> int:
        """Owners of this process who can actually work it on d (planning view:
        'undecided' counts as available; someone covering another brand does not)."""
        brand = self.c.proc[pid].brand_id
        n = 0
        for e in self.c.primaries[pid]:
            if e == exclude:
                continue
            if self.st(e, d) in REST:
                continue
            if self.covering_brands(e, d) - {brand}:
                continue
            n += 1
        return n

    def have(self, pid, d, exclude=None) -> int:
        return self.working_primaries(pid, d, exclude) + len(self.r.covers.get((pid, d), []))

    def deficit(self, pid, d) -> int:
        return max(0, self.c.required(pid, d) - self.have(pid, d))

    # ------------------------------------------------------------------
    # cover logic
    # ------------------------------------------------------------------
    def eligible(self, cand, pid, d) -> bool:
        c = self.c
        if cand in c.primaries[pid]:
            return False
        if self.st(cand, d) in REST:                       # off / leave / holiday
            return False
        brand = c.proc[pid].brand_id
        if self.covering_brands(cand, d) - {brand}:        # one brand per day
            return False
        if cand in self.r.covers.get((pid, d), []):
            return False
        for q in c.emp_procs.get(cand, []):                # own work must stay covered
            if c.is_open(q, d) and self.have(q, d, exclude=cand) < c.required(q, d):
                return False
        return True

    def candidates(self, pid, d) -> List[int]:
        """Eligible backups, best first: non-leads before pod leads (lead = last
        resort), then whoever has covered the fewest days so far (fair load)."""
        c = self.c
        assigned = set(c.backups[pid])
        pod = c.brand[c.proc[pid].brand_id].pod_id
        # Assigned backups first; then same-pod colleagues who happen to be free.
        # A non-assigned colleague carries a small penalty (+EXTRA) so the named
        # backups are still preferred, but nobody is worked to the bone while a free
        # colleague sits idle.
        pool = [x.id for x in c.ds.employees
                if (x.id in assigned or x.pod_id == pod) and self.eligible(x.id, pid, d)]
        return sorted(pool, key=lambda x: (
            c.emp[x].is_pod_lead,
            self.cover_days(x) + (0 if x in assigned else self.EXTRA), x))

    def cover_brand(self, brand_id, d) -> List[int]:
        """Close every gap of this brand on day d. Returns process ids still short."""
        unresolved = []
        for pid in self.c.brand_procs[brand_id]:
            while self.deficit(pid, d) > 0:
                cands = self.candidates(pid, d)
                if not cands:
                    unresolved.append(pid)
                    break
                reuse = [x for x in cands if brand_id in self.covering_brands(x, d)]
                pick = (reuse or cands)[0]    # one person can cover a whole brand
                self.r.covers.setdefault((pid, d), []).append(pick)
        return unresolved

    # ------------------------------------------------------------------
    # weekly-off planning
    # ------------------------------------------------------------------
    def snapshot(self):
        return dict(self.r.status), {k: list(v) for k, v in self.r.covers.items()}

    def restore(self, snap):
        self.r.status, self.r.covers = dict(snap[0]), {k: list(v) for k, v in snap[1].items()}

    def try_weekday(self, e, w) -> int:
        """Give employee e a weekly off on weekday w for the whole month.
        Returns how many of those days ended up NOT properly covered."""
        c = self.c
        failed = 0
        for d in self.days:
            if d.weekday() != w or self.st(e.id, d) is not None:
                continue                      # already a leave/holiday: rest day anyway
            if self.covering_brands(e.id, d):  # they are someone's cover that day
                failed += 1
                continue
            self.r.status[(e.id, d)] = Status.WEEKLY_OFF
            affected = {c.proc[p].brand_id for p in c.emp_procs.get(e.id, [])
                        if c.is_open(p, d)}
            if any(self.cover_brand(b, d) for b in affected):
                failed += 1
        return failed

    def plan_weekly_offs(self):
        c = self.c
        for e in c.ds.employees:
            if c.natural_sunday_off(e.id):
                self.r.off_weekday[e.id] = 6   # Mon-Sat calendar: Sunday is the off

        def sole_owner(e):
            return any(len(c.primaries[p]) == 1 for p in c.emp_procs.get(e.id, []))

        todo = [e for e in c.ds.employees if e.id not in self.r.off_weekday]
        # Pod leads go FIRST. They own nothing, so their off day never opens a gap, but
        # they are the backup of last resort for many processes: if they were planned
        # last, cover duty would already have eaten every weekday and they would end up
        # with no day off. Fixing their off day first keeps them out of cover that day.
        todo.sort(key=lambda e: (not e.is_pod_lead, 0 if sole_owner(e) else 1,
                                 -len(c.emp_procs.get(e.id, [])), e.id))

        pod_load = defaultdict(int)            # (pod, weekday) -> people already off
        for e in todo:
            pref = e.preferred_off_weekday
            others = sorted((w for w in range(7) if w != pref),
                            key=lambda w: (pod_load[(e.pod_id, w)], w))
            tries = ([pref] if pref is not None else []) + others

            best = None
            chosen = None
            for w in tries:
                snap = self.snapshot()
                failed = self.try_weekday(e, w)
                if failed == 0:
                    chosen = w
                    break
                if best is None or failed < best[0]:
                    best = (failed, w)
                self.restore(snap)
            if chosen is None:                 # nothing fully works: least-bad day,
                chosen = best[1]               # the validator will report what is left
                self.try_weekday(e, chosen)
            self.r.off_weekday[e.id] = chosen
            pod_load[(e.pod_id, chosen)] += 1

    # ------------------------------------------------------------------
    def run(self) -> Roster:
        c = self.c
        for e in c.ds.employees:                                  # 1. FIXED
            for d in self.days:
                s = c.fixed_status(e.id, d)
                if s is not None:
                    self.r.status[(e.id, d)] = s
        for d in self.days:                                       # 2. LEAVE COVER
            for b in c.ds.brands:
                self.cover_brand(b.id, d)
        self.plan_weekly_offs()                                   # 3. WEEKLY OFFS
        for e in c.ds.employees:                                  # 4. FILL
            for d in self.days:
                self.r.status.setdefault((e.id, d), Status.WORK)
        return self.r


def generate_roster(ds: Dataset, year: int, month: int) -> Roster:
    return Planner(ds, year, month).run()
