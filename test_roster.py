"""Smoke tests for the scheduling core. Run:  python -m unittest -v
(no extra packages needed)"""
import unittest
from datetime import date

from changes import evaluate_leave
from models import AssignmentRole, LeaveType
from scheduler import generate_roster
from seed_data import build_dataset
from validator import MANDATORY, validate


class RosterTests(unittest.TestCase):
    def setUp(self):
        self.ds = build_dataset()
        self.roster = generate_roster(self.ds, 2026, 11)

    def test_dataset_shape(self):
        self.assertGreaterEqual(len(self.ds.employees), 30)
        owners = {}
        for a in self.ds.assignments:
            if a.role == AssignmentRole.PRIMARY:
                pr = next(p for p in self.ds.processes if p.id == a.process_id)
                owners.setdefault(pr.brand_id, set()).add(a.employee_id)
        single = sum(1 for v in owners.values() if len(v) == 1)
        self.assertGreaterEqual(single / len(self.ds.brands), 0.75)

    def test_generated_roster_has_no_mandatory_issue(self):
        bad = [x for x in validate(self.ds, self.roster) if x.severity == MANDATORY]
        self.assertEqual(bad, [], [x.message for x in bad])

    def test_validator_catches_a_broken_roster(self):
        # Force a sole owner of a 365-day process to be off with no cover: must be flagged.
        proc = next(p for p in self.ds.processes if p.calendar.value == "365")
        owner = next(a.employee_id for a in self.ds.assignments
                     if a.process_id == proc.id and a.role == AssignmentRole.PRIMARY)
        d = date(2026, 11, 10)
        self.roster.covers.pop((proc.id, d), None)
        from models import Status
        self.roster.status[(owner, d)] = Status.WEEKLY_OFF
        codes = {x.code for x in validate(self.ds, self.roster)}
        self.assertIn("COVERAGE_GAP", codes)

    def test_leave_preview_does_not_change_the_published_roster(self):
        before = dict(self.roster.status)
        emp = self.ds.employees[5]
        evaluate_leave(self.ds, self.roster, emp.id, date(2026, 11, 10),
                       date(2026, 11, 12), LeaveType.PLANNED)
        self.assertEqual(before, self.roster.status)


if __name__ == "__main__":
    unittest.main()
