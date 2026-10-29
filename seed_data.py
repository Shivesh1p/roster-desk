"""Realistic (fictional) sample dataset.

Shape of the data (all of this is an ASSUMPTION, editable by the manager later):
  * 4 pods, each with a pod lead.
  * 25 brands: 20 single-resource (80%) + 5 multi-employee (20%).
      - Two employees each own TWO small brands, so brands > owners.
      - Multi-employee brands mix "split processes" and "shared process" setups.
  * 34 employees = 4 pod leads + 18 single-brand owners + 12 multi-brand staff.
  * Pod leads are last-resort BACKUP for every 365-day process in their pod.
  * Holidays / leaves are fictional but modelled on Nov 2026 so the demo month has
    something to chew on. Holiday dates should be verified before real use.
"""
from datetime import date

from models import (Assignment, AssignmentRole, Brand, CalendarType, Dataset,
                    Employee, Holiday, Leave, LeaveType, Pod, Process)

A = CalendarType.ALL_365
H = CalendarType.NO_HOLIDAYS
S = CalendarType.NO_SUN_HOLIDAYS

FIRST = ["Aarav", "Ishita", "Rohan", "Meera", "Kabir", "Ananya", "Vikram", "Sana",
         "Arjun", "Neha", "Karan", "Priya", "Rahul", "Divya", "Siddharth", "Pooja",
         "Aditya", "Kavya", "Manish", "Riya", "Nikhil", "Tanvi", "Varun", "Shreya",
         "Yash", "Pallavi", "Deepak", "Aishwarya", "Mohit", "Sneha", "Ritesh",
         "Naina", "Gaurav", "Jyoti", "Tushar", "Farhan"]
LAST = ["Sharma", "Iyer", "Mehta", "Nair", "Khan", "Reddy", "Joshi", "Patel",
        "Gupta", "Verma", "Kulkarni", "Singh", "Das", "Bose", "Shetty", "Menon",
        "Chopra", "Rao", "Desai", "Malhotra", "Pillai", "Saxena", "Bhatt", "Naidu",
        "Kapoor", "Jain", "Mishra", "Sen", "Fernandes", "Thakur", "Agarwal",
        "Ghosh", "Yadav", "Pawar", "Banerjee", "Ansari"]

POD_NAMES = ["Pod Alpha", "Pod Bravo", "Pod Charlie", "Pod Delta"]

# (brand, pod index, [(process, calendar)], owner key). Same owner key = same person.
SINGLE_BRANDS = [
    ("Kaapi Culture", 0, [("CS", H), ("ACC", H)], "o1"),
    ("Rangrez Home", 0, [("CS", A), ("NDR", H)], "o2"),
    ("Veda Naturals", 0, [("CS", S), ("ACC", S)], "o3"),
    ("Masala Lane", 0, [("CS", H), ("RET", H)], "o4"),
    ("Tilt Eyewear", 0, [("CS", S)], "o4"),            # o4 owns two brands
    ("Bloom Bath", 1, [("CS", A), ("ACC", H)], "o5"),
    ("Desi Denim", 1, [("CS", H), ("NDR", H)], "o6"),
    ("Chai Tales", 1, [("CS", S), ("ACC", S), ("RET", S)], "o7"),
    ("Orbit Gadgets", 1, [("CS", A), ("NDR", A)], "o8"),
    ("Saath Kids", 1, [("CS", H), ("ACC", H)], "o9"),
    ("Ghee Gold", 2, [("CS", H), ("NDR", H)], "o10"),
    ("Loom & Lace", 2, [("CS", S), ("ACC", S)], "o11"),
    ("FitFuel", 2, [("CS", A), ("ACC", H)], "o12"),
    ("Mitti Pots", 2, [("CS", H)], "o13"),
    ("Aura Candles", 2, [("CS", S), ("RET", S)], "o13"),  # o13 owns two brands
    ("Jhankar Jewels", 3, [("CS", H), ("ACC", H), ("NDR", H)], "o14"),
    ("Snackaroo", 3, [("CS", A), ("NDR", H)], "o15"),
    ("Navrang Ethnic", 3, [("CS", S), ("ACC", S)], "o16"),
    ("PureRoots Ayurveda", 3, [("CS", H), ("RET", H)], "o17"),
    ("TrekMate Gear", 3, [("CS", H), ("ACC", S)], "o18"),
]

# (brand, pod index, [(process, calendar, min_staff, {weekday: min_staff})],
#  {employee key: [process names]})
MULTI_BRANDS = [
    # Split processes: one person per process
    ("Glowkind Skincare", 0,
     [("CS", A, 1, {}), ("ACC", H, 1, {}), ("NDR", S, 1, {})],
     {"m1": ["CS"], "m2": ["ACC"], "m3": ["NDR"]}),
    # Shared CS (two people), one of them also does ACC; CS needs 2 on weekends
    ("Urban Thread Co", 1,
     [("CS", A, 1, {5: 2, 6: 2}), ("ACC", H, 1, {})],
     {"m4": ["CS"], "m5": ["CS", "ACC"]}),
    ("Nutrimunch Foods", 2,
     [("CS", A, 1, {}), ("ACC", H, 1, {}), ("NDR", H, 1, {})],
     {"m6": ["CS"], "m7": ["ACC"], "m8": ["NDR"]}),
    # Overlap: m10 does both processes, m9 shares CS
    ("Pawfect Pets", 3,
     [("CS", A, 1, {}), ("RET", S, 1, {})],
     {"m9": ["CS"], "m10": ["CS", "RET"]}),
    # CS needs 2 people on Mondays (sale-day spike)
    ("Zenfit Wellness", 0,
     [("CS", H, 1, {0: 2}), ("ACC", S, 1, {})],
     {"m11": ["CS", "ACC"], "m12": ["CS"]}),
]

HOLIDAYS = [
    Holiday(date(2026, 10, 2), "Gandhi Jayanti"),
    Holiday(date(2026, 10, 20), "Dussehra"),
    Holiday(date(2026, 11, 8), "Diwali"),
    Holiday(date(2026, 11, 24), "Guru Nanak Jayanti"),
    Holiday(date(2026, 12, 25), "Christmas"),
    Holiday(date(2027, 1, 26), "Republic Day"),
]

# (employee key, start, end, type, note). Dates are Nov 2026.
LEAVES = [
    ("o3", date(2026, 11, 2), date(2026, 11, 4), LeaveType.PLANNED, "Family function"),
    ("o7", date(2026, 11, 16), date(2026, 11, 18), LeaveType.PLANNED, "Travel"),
    ("o10", date(2026, 11, 20), date(2026, 11, 20), LeaveType.COMP_OFF, "Worked Diwali weekend"),
    ("m3", date(2026, 11, 12), date(2026, 11, 12), LeaveType.PLANNED, "Medical appointment"),
    ("o16", date(2026, 11, 23), date(2026, 11, 27), LeaveType.PLANNED, "Wedding"),
    ("m8", date(2026, 11, 6), date(2026, 11, 6), LeaveType.COMP_OFF, "Worked last Sunday"),
]

# Cross-trained floaters: employee key -> pod index they can float within.
FLOATERS = {"m12": 0, "m4": 1, "m9": 3}

PREF_OFF_CYCLE =[6, 0, None, 2, 5, 1, None, 3, 4]  # 6=Sun ... None = no preference


def build_dataset() -> Dataset:
    names = [f"{f} {LAST[(i * 7) % len(LAST)]}" for i, f in enumerate(FIRST)]
    name_iter = iter(names)

    pods, employees, brands, processes, assignments = [], [], [], [], []
    key_to_emp = {}
    next_emp_id = [1]
    next_brand_id = [1]
    next_proc_id = [1]

    def new_employee(pod_idx, lead=False):
        i = next_emp_id[0]
        next_emp_id[0] += 1
        e = Employee(id=i, name=next(name_iter), pod_id=pod_idx + 1, is_pod_lead=lead,
                     preferred_off_weekday=PREF_OFF_CYCLE[i % len(PREF_OFF_CYCLE)])
        employees.append(e)
        return e

    # Pods + leads (leads are employees too)
    for p, pname in enumerate(POD_NAMES):
        lead = new_employee(p, lead=True)
        pods.append(Pod(id=p + 1, name=pname, lead_id=lead.id))

    def owner(key, pod_idx):
        if key not in key_to_emp:
            key_to_emp[key] = new_employee(pod_idx)
        return key_to_emp[key]

    def new_brand(name, pod_idx):
        b = Brand(id=next_brand_id[0], name=name, pod_id=pod_idx + 1)
        next_brand_id[0] += 1
        brands.append(b)
        return b

    def new_process(brand, pname, cal, min_staff=1, overrides=None):
        pr = Process(id=next_proc_id[0], brand_id=brand.id, name=pname, calendar=cal,
                     min_staff=min_staff, min_staff_overrides=dict(overrides or {}))
        next_proc_id[0] += 1
        processes.append(pr)
        return pr

    # Single-resource brands: one dedicated person handles every process
    for bname, pod_idx, procs, okey in SINGLE_BRANDS:
        emp = owner(okey, pod_idx)
        brand = new_brand(bname, pod_idx)
        for pname, cal in procs:
            pr = new_process(brand, pname, cal)
            assignments.append(Assignment(emp.id, pr.id, AssignmentRole.PRIMARY))

    # Multi-employee brands
    for bname, pod_idx, procs, staff in MULTI_BRANDS:
        brand = new_brand(bname, pod_idx)
        by_name = {}
        for pname, cal, ms, ov in procs:
            by_name[pname] = new_process(brand, pname, cal, ms, ov)
        for ekey, pnames in staff.items():
            emp = owner(ekey, pod_idx)
            for pn in pnames:
                assignments.append(Assignment(emp.id, by_name[pn].id, AssignmentRole.PRIMARY))

    # ---- Backups (who may be pulled in to cover a gap) ----------------------
    brand_pod = {b.id: b.pod_id for b in brands}
    lead_of = {p.id: p.lead_id for p in pods}
    primary_of = {}
    for a in assignments:
        primary_of.setdefault(a.process_id, set()).add(a.employee_id)
    brand_primaries = {}
    for pr in processes:
        brand_primaries.setdefault(pr.brand_id, set()).update(primary_of[pr.id])

    # (1) Pod lead is the last-resort backup on EVERY process in their pod.
    for pr in processes:
        assignments.append(Assignment(lead_of[brand_pod[pr.brand_id]], pr.id,
                                      AssignmentRole.BACKUP))

    # (2) Cross-trained "floaters": staff of a brand that shares a process (so they
    #     have slack) can cover the single-owner brands in their pod.
    for fkey, pod_idx in FLOATERS.items():
        f = key_to_emp[fkey]
        for pr in processes:
            if (brand_pod[pr.brand_id] == pod_idx + 1
                    and len(brand_primaries[pr.brand_id]) == 1
                    and f.id not in primary_of[pr.id]):
                assignments.append(Assignment(f.id, pr.id, AssignmentRole.BACKUP))

    # (3) One same-pod colleague as extra backup on each 365-day process (rotating).
    rotate = {}
    for pr in processes:
        if pr.calendar != A:
            continue
        pod_id = brand_pod[pr.brand_id]
        colleagues = [e for e in employees
                      if e.pod_id == pod_id and not e.is_pod_lead
                      and e.id not in primary_of[pr.id]]
        if colleagues:
            idx = rotate.get(pod_id, 0)
            assignments.append(Assignment(colleagues[idx % len(colleagues)].id, pr.id,
                                          AssignmentRole.BACKUP))
            rotate[pod_id] = idx + 1

    leaves = [Leave(key_to_emp[k].id, s, e, t, note) for k, s, e, t, note in LEAVES]

    return Dataset(pods=pods, employees=employees, brands=brands, processes=processes,
                   assignments=assignments, holidays=list(HOLIDAYS), leaves=leaves)
