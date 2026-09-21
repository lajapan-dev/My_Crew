import tempfile
import unittest
from pathlib import Path

from crew import db
from crew.config import Job


def mkjob(i, cat="bugfix", risk="low"):
    return Job(f"20260101-{i:03d}", f"t{i}", cat, risk, "S", "2026-01-01T00:00:00")


class DbTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = db.connect(Path(self.tmp.name) / "crew.db")

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_decision_unique_per_job(self):
        db.insert_job(self.conn, mkjob(1))
        db.upsert_decision(self.conn, "20260101-001", "rule", "both", "both", {}, "r", False, None)
        with self.assertRaises(ValueError):
            db.upsert_decision(self.conn, "20260101-001", "rule", "claude", "both", {}, "r", False, None)
        db.upsert_decision(self.conn, "20260101-001", "gemini", "claude", "both", {}, "r2", True, 0.8, force=True)
        d = db.get_decision(self.conn, "20260101-001")
        self.assertEqual(d["decision"], "claude")
        self.assertEqual(d["overrode_rule"], 1)

    def test_stats_aggregate(self):
        for i in range(1, 4):
            db.insert_job(self.conn, mkjob(i))
        # claude: 2 accepted, 1 rejected; tests 10/12
        r1 = db.insert_run(self.conn, "20260101-001", "claude", "engineer", 0)
        db.finish_run(self.conn, r1, outcome="success", tests_total=5, tests_passed=5, duration_s=10)
        db.insert_review(self.conn, r1, "accept")
        r2 = db.insert_run(self.conn, "20260101-002", "claude", "engineer", 0)
        db.finish_run(self.conn, r2, outcome="success", tests_total=4, tests_passed=2, duration_s=20)
        db.insert_review(self.conn, r2, "reject")
        r3 = db.insert_run(self.conn, "20260101-003", "claude", "engineer", 1)
        db.finish_run(self.conn, r3, outcome="success", tests_total=3, tests_passed=3, duration_s=30)
        db.insert_review(self.conn, r3, "accept")
        # codex: one unreviewed (should not count as n), one running (excluded)
        r4 = db.insert_run(self.conn, "20260101-001", "codex", "engineer", 0)
        db.finish_run(self.conn, r4, outcome="success", tests_total=2, tests_passed=2)
        db.insert_run(self.conn, "20260101-002", "codex", "engineer", 0)
        rows = {r["engine"]: r for r in db.engine_stats(self.conn, "bugfix")}
        self.assertEqual(rows["claude"]["runs"], 3)
        self.assertEqual(rows["claude"]["reviewed"], 3)
        self.assertEqual(rows["claude"]["accepts"], 2)
        self.assertEqual(rows["claude"]["tests_total"], 12)
        self.assertEqual(rows["claude"]["tests_passed"], 10)
        self.assertAlmostEqual(rows["claude"]["avg_revisions"], 1 / 3)
        self.assertEqual(rows["codex"]["runs"], 1)
        self.assertEqual(rows["codex"]["reviewed"], 0)
        self.assertEqual(db.engine_stats(self.conn, "docs"), [])

    def test_latest_review_wins(self):
        db.insert_job(self.conn, mkjob(1))
        r = db.insert_run(self.conn, "20260101-001", "claude", "engineer", 0)
        db.finish_run(self.conn, r, outcome="success")
        db.insert_review(self.conn, r, "reject")
        db.insert_review(self.conn, r, "accept")
        row = db.engine_stats(self.conn)[0]
        self.assertEqual(row["accepts"], 1)
        self.assertEqual(db.count_prior_runs(self.conn, "20260101-001", "claude"), 1)


if __name__ == "__main__":
    unittest.main()
