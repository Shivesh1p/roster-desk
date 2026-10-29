"""Generate the November 2026 roster, validate it, and print a company-wide grid.

Run:  python run_demo.py
Legend:  W work   o weekly off   L leave   C comp-off   H public holiday
         * = working AND pulled in as cover for another process that day
"""
from collections import Counter

from models import Status
from scheduler import generate_roster
from seed_data import build_dataset
from validator import MANDATORY, PREFERENCE, validate

YEAR, MONTH = 2026, 11
SYMBOL = {Status.WORK: "W", Status.WEEKLY_OFF: "o", Status.LEAVE: "L",
          Status.COMP_OFF: "C", Status.HOLIDAY: "H"}


def print_grid(ds, roster):
    days = roster.days()
    cover_on = {(e, d) for (_, d), lst in roster.covers.items() for e in lst}
    print("\n" + " " * 22 + " ".join(f"{d.day:>2}" for d in days))
    print(" " * 22 + " ".join(f"{'MTWTFSS'[d.weekday()]:>2}" for d in days))
    for pod in ds.pods:
        print(f"--- {pod.name} ---")
        for e in [x for x in ds.employees if x.pod_id == pod.id]:
            cells = []
            for d in days:
                s = SYMBOL[roster.status[(e.id, d)]]
                if (e.id, d) in cover_on:
                    s = "*"
                cells.append(f"{s:>2}")
            tag = " (lead)" if e.is_pod_lead else ""
            print(f"{(e.name + tag)[:21]:<22}" + " ".join(cells))


def main():
    ds = build_dataset()
    roster = generate_roster(ds, YEAR, MONTH)
    conflicts = validate(ds, roster)

    print_grid(ds, roster)

    mand = [x for x in conflicts if x.severity == MANDATORY]
    pref = [x for x in conflicts if x.severity == PREFERENCE]
    print(f"\n=== {YEAR}-{MONTH:02d} validation: {len(mand)} mandatory issue(s), "
          f"{len(pref)} preference note(s) ===")
    for x in mand:
        print(f"[{x.code}] {x.message}")
    by_code = Counter(x.code for x in mand)
    if by_code:
        print("Mandatory by type:", dict(by_code))

    emp = {e.id: e for e in ds.employees}
    load = Counter(e for lst in roster.covers.values() for e in lst)
    print("\nCover days per person (top 8):",
          [(emp[e].name, n) for e, n in load.most_common(8)])
    print(f"Preference notes (soft, coverage came first): {len(pref)}")


if __name__ == "__main__":
    main()
