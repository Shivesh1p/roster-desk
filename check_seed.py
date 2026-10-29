"""Sanity-check the sample data and show the single-resource risk picture.

Run:  python check_seed.py
"""
from collections import defaultdict

from calendar_rules import holiday_dates, is_open, month_days, required_staff
from models import AssignmentRole, CalendarType
from seed_data import build_dataset

YEAR, MONTH = 2026, 11


def main():
    ds = build_dataset()
    emp = {e.id: e for e in ds.employees}
    brand = {b.id: b for b in ds.brands}
    proc = {p.id: p for p in ds.processes}
    hol = holiday_dates(ds.holidays)

    # --- Basic shape -------------------------------------------------
    print(f"Employees: {len(ds.employees)} | Pods: {len(ds.pods)} | "
          f"Brands: {len(ds.brands)} | Processes: {len(ds.processes)}")

    primaries = defaultdict(set)   # brand_id -> employee ids with PRIMARY work
    for a in ds.assignments:
        if a.role == AssignmentRole.PRIMARY:
            primaries[proc[a.process_id].brand_id].add(a.employee_id)
    single = [b for b in ds.brands if len(primaries[b.id]) == 1]
    multi = [b for b in ds.brands if len(primaries[b.id]) > 1]
    print(f"Single-resource brands: {len(single)} ({100 * len(single) // len(ds.brands)}%) | "
          f"Multi-employee brands: {len(multi)}")

    # --- Integrity checks --------------------------------------------
    problems = []
    for p in ds.processes:
        if not any(a.process_id == p.id and a.role == AssignmentRole.PRIMARY
                   for a in ds.assignments):
            problems.append(f"Process {brand[p.brand_id].name}/{p.name} has no PRIMARY employee")
    for e in ds.employees:
        if not e.is_pod_lead and not any(a.employee_id == e.id for a in ds.assignments):
            problems.append(f"{e.name} has no assignment")
    print("Integrity:", "OK" if not problems else problems)

    # --- The structural risk: single owner + 365-day process ---------
    print("\nHigh-risk (one owner, 365-day process -> weekly off MUST come from a backup):")
    for b in single:
        for p in ds.processes:
            if p.brand_id == b.id and p.calendar == CalendarType.ALL_365:
                owner = emp[next(iter(primaries[b.id]))]
                backups = [emp[a.employee_id].name for a in ds.assignments
                           if a.process_id == p.id and a.role == AssignmentRole.BACKUP]
                print(f"  {b.name:<16} {p.name:<4} owner={owner.name:<18} backups={backups}")

    # --- Demand for the demo month -----------------------------------
    days = month_days(YEAR, MONTH)
    open_counts = [sum(1 for p in ds.processes if is_open(p, d, hol)) for d in days]
    need = [sum(required_staff(p, d, hol) for p in ds.processes) for d in days]
    print(f"\n{YEAR}-{MONTH:02d}: open processes per day min/max = "
          f"{min(open_counts)}/{max(open_counts)}; "
          f"staff-slots needed per day min/max = {min(need)}/{max(need)}")
    print("Holidays this month:", [(h.day.isoformat(), h.name) for h in ds.holidays
                                   if h.day.month == MONTH and h.day.year == YEAR])
    print("Leaves this month:")
    for lv in ds.leaves:
        print(f"  {emp[lv.employee_id].name:<18} {lv.start} -> {lv.end} {lv.type.value}")


if __name__ == "__main__":
    main()
