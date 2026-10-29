# Roster Desk — Smart Roster Management System

A browser-based tool that helps an operations manager **plan, generate, validate and change** monthly rosters for a team spread across D2C brands, processes and pods.

Built for the Datastraw Tech Internship assessment. Stack: Python 3 · FastAPI · plain HTML/JS (no build step).
Built with AI assistance (Claude). I own the design decisions described below and can walk through every file.

- **Live app:** `<add deployed URL>`
- **Demo video:** `<add link>`

## What it does

| Need from the brief | Where |
|---|---|
| ≥ 30 employees, brands, processes, pods, pod leads, shared / multi-brand staff | `seed_data.py` (34 employees, 4 pods, 25 brands, 52 processes) |
| Operating calendars (365 / every day except holidays / Mon–Sat except holidays), min staffing, per-weekday overrides | `models.py`, `calendar_rules.py` |
| Monthly roster generation | `scheduler.py` |
| Conflict and coverage-gap detection (mandatory vs preference) | `validator.py` |
| Company / Pod / Brand / Process / Employee views | `static/index.html` |
| Handling a change without rebuilding the roster | `changes.py` (leave, cancelled leave, manual edit — always **preview first**) |
| Add / edit / remove pods, employees, brands, processes, assignments, holidays with **no code change** | Setup tab → `/api/...` endpoints in `app.py` |
| CSV export | `/api/roster.csv` |

## Run locally

```bash
pip install -r requirements.txt
uvicorn app:app --reload          # open http://127.0.0.1:8000
python run_demo.py                # same engine in the terminal (text grid)
python -m unittest -v             # tests
```

No environment variables are needed (see `.env.example`).

## Deploy (Render, free tier)

Push to GitHub → Render → New Web Service → pick the repo. `render.yaml` already holds the build and start commands (`pip install -r requirements.txt`, `uvicorn app:app --host 0.0.0.0 --port $PORT`).
The free tier sleeps when idle, so open the URL once before showing it to someone.

## How to try the "change" demo

1. Open **Company** view, then **Change Desk → Leave / comp-off**.
2. Pick the owner of a single-person brand with a 365-day process (e.g. *Manish Desai* — Snackaroo), choose 10–12 Nov, **Preview impact**.
3. The preview lists each affected brand/process/day as *covered by backup*, *still fine with remaining staff*, or *needs your decision* — with options. Nothing is saved until you apply it.

## Architecture

```
seed_data.py ──► models.py (plain dataclasses) ──► context.py (read-only lookups)
                                   │
          scheduler.py  (generate)  │  validator.py (re-check from scratch)
                                   ▼
                    changes.py (preview / apply a change)
                                   ▼
                   app.py (FastAPI)  ◄──►  static/index.html
```

Key decision: **the validator does not trust the generator.** It re-derives coverage from the final statuses, so it works the same on a generated roster, a manually edited one, or one after a change.

## Assumptions (all configurable as data)

- Calendar types: `365`, `NO_HOLIDAYS` (every day except public holidays), `NO_SUN_HOLIDAYS` (Mon–Sat except holidays).
- Each employee gets **one fixed weekday off** for the month (Sunday automatically for people whose processes are all Mon–Sat). Holidays on which all of a person's processes are closed are rest days.
- Max 6 consecutive working days; at least one rest day in every full Mon–Sun week.
- A person can cover only **one other brand per day**. Pod leads are the backup of last resort.
- Leave on a day the person is already on weekly off costs nothing and is noted as such.
- The start of the month assumes nothing about the previous month's tail.
- Names, brands and holiday dates are fictional / illustrative; holiday dates should be verified before real use.
- State is **in memory**, seeded from `seed_data.py`. A restart resets it (the "Reset demo data" button does the same).

## Tell us how you think

**1. How did I model employees, brands, processes, pods and their relationships?**
A pod has employees and one lead. A brand belongs to a pod. A process belongs to a brand and carries its own *operating calendar*, *minimum staff* and optional per-weekday minimums. People are linked to processes through an **Assignment** (employee ↔ process, role `PRIMARY` or `BACKUP`). Because the link is at process level, one person can own every process of a brand, a brand can split processes across people, two people can share a process, and one person can span several brands — all without special cases. I kept a process's operating calendar separate from a person's schedule on purpose: the first says *when coverage is required*, the second says *when someone is working*.

**2. How does the system generate a roster and decide it satisfies the constraints?**
Four phases: (1) place fixed days — holidays, days a person's processes are closed, approved leave and comp-offs; (2) cover the gaps those create using backups; (3) give each person one weekly-off weekday, trying their preferred day first but only keeping a day if every process they own stays covered; (4) everything else is a working day. Then a **separate validator** re-checks the finished roster: coverage per open process-day, double-booked cover, leave honoured, max consecutive days, one rest day per week. Anything left is reported, never hidden.

**3. Single-resource brands vs. brands with several employees?**
They are the same data model; the difference shows up as risk. For a sole owner every weekly off is a coverage gap by definition, so those people are planned **first**, before the flexible ones, and their off-day must be covered by a backup. In multi-employee brands, other people working the same process already count toward the minimum, so the planner picks off-days that keep `minimum staff` satisfied (including days that need 2 on a busy weekday).

**4. What if someone who handles all of a brand's processes is unavailable on a required day?**
The change engine flags every affected process-day and tries to fill it from assigned backups (non-leads first, pod lead last, least-loaded first, one brand per person per day). If nobody is free it marks the day **UNCOVERED** and offers options, e.g. "ask X (same pod) to work their weekly off and give a comp-off". It does not apply that option itself, because that is a human decision.

**5. How are conflicting requirements or insufficient staffing handled?**
Rules are split into **mandatory** (coverage, approved leave, max consecutive days, weekly rest, no double-booking) and **preference** (preferred off-day, workload balance). Mandatory always wins; a missed preference is shown as a soft note. Unresolvable problems are listed in plain sentences ("*X needs 1 on Tue 10 Nov but 0 available. Owner is on leave; backups: …*"). A `CAPACITY_WARNING` also flags people who are the safety net too often, which is a sign a pod needs another backup.

**6. What did I automate and what is left to humans — and why?**
Automated: generating the roster, validating it, finding and ranking cover, previewing the impact of a change. Left to the manager: approving leave, asking someone to work a weekly off, accepting an unresolved gap, and publishing. These are judgement calls about people (fairness, goodwill, client agreements) and I would not want software to take them silently.

**7. If the company doubled its team and brands, what would change?**
Persistence (Postgres) and users/roles instead of in-memory state; generate per pod and in the background; index lookups the planner currently scans (cover per day, brand per person); and for tight pods, a constraint solver (e.g. OR-Tools CP-SAT) for global optimisation, kept behind the same validator so correctness doesn't depend on the solver.

**8. With one more week, what would I improve first?**
Cover fairness. Today the fixed-weekday approach is easy to explain, but a few people (Rohan Shetty, Ritesh Agarwal) end up covering a large share of days — the app warns about it, but it should be balanced, e.g. by allowing a flagged "stretched" cover from sole owners with spare capacity and by rotating weekly offs for fairness. After that: a persistent database, approval workflow for pod leads, and notifications when a published roster changes.

## Known limitations

- In-memory state (no database, no login).
- Weekly off is the same weekday all month, not rotated.
- Cover load is uneven for a few backups (warned in the UI).
- Holiday dates and names are illustrative.
