import tempfile
import unittest
from pathlib import Path

from crew import db
from crew.config import DEFAULT_SETTINGS, Job
from crew.dispatcher import build_gemini_prompt, decide, gather_stats, validate_gemini
from crew.engines.gemini_client import extract_json
from crew.scoring import RuleDecision, rule_decide


class DispatcherTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.conn = db.connect(self.root / "crew.db")
        self.settings = {k: dict(v) for k, v in DEFAULT_SETTINGS.items()}
        self.companies = {}

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def seed(self, engine, n_ok, n_ng, cat="bugfix"):
        for i in range(n_ok + n_ng):
            jid = f"{engine}-{cat}-{i}"
            db.insert_job(self.conn, Job(jid, jid, cat, "low", "S", "2026-01-01T00:00:00"))
            r = db.insert_run(self.conn, jid, engine, "engineer", 0)
            db.finish_run(self.conn, r, outcome="success", tests_total=2, tests_passed=2)
            db.insert_review(self.conn, r, "accept" if i < n_ok else "reject")

    def test_cold_start_rule_only(self):
        job = Job("j1", "t", "bugfix", "low", "S", "2026-01-01T00:00:00")
        out = decide(self.conn, self.settings, self.companies, job, self.root,
                     available=["claude", "codex"], use_gemini=False)
        self.assertEqual(out.decision, "both")
        self.assertEqual(out.decided_by, "rule")
        self.assertTrue(out.rule.forced)

    def test_data_driven_winner_without_gemini(self):
        self.seed("claude", 9, 1)
        self.seed("codex", 4, 6)
        job = Job("j2", "t", "bugfix", "low", "S", "2026-01-01T00:00:00")
        out = decide(self.conn, self.settings, self.companies, job, self.root,
                     available=["claude", "codex"], use_gemini=False)
        self.assertEqual(out.decision, "claude")
        self.assertGreater(out.rule.scores["claude"], out.rule.scores["codex"])

    def test_forced_rule_skips_gemini_even_if_enabled(self):
        job = Job("j3", "t", "bugfix", "high", "S", "2026-01-01T00:00:00")
        out = decide(self.conn, self.settings, self.companies, job, self.root,
                     available=["claude", "codex"], use_gemini=True)
        self.assertEqual(out.decision, "both")
        self.assertIn("固定ルール", out.note)

    def test_stats_are_category_scoped(self):
        self.seed("claude", 5, 0, cat="docs")
        st = gather_stats(self.conn, "bugfix", ["claude", "codex"])
        self.assertEqual(st["claude"].n, 0)
        st = gather_stats(self.conn, "docs", ["claude", "codex"])
        self.assertEqual(st["claude"].n, 5)


class GeminiValidationTest(unittest.TestCase):
    def rule(self, decision="claude", forced=False):
        return RuleDecision(decision, "reason", forced, {"claude": 0.8, "codex": 0.5}, {})

    def test_agree(self):
        out, why = validate_gemini({"decision": "claude", "confidence": 0.9, "reason": "ok"}, self.rule(), ["claude", "codex", "both"])
        self.assertEqual(out.decision, "claude")
        self.assertFalse(out.overrode_rule)
        self.assertEqual(out.confidence, 0.9)

    def test_override_needs_reason(self):
        out, why = validate_gemini({"decision": "codex", "reason": ""}, self.rule(), ["claude", "codex", "both"])
        self.assertIsNone(out)
        out, why = validate_gemini({"decision": "codex", "reason": "codex は直近5件でテスト通過率100%、claude は80%"},
                                   self.rule(), ["claude", "codex", "both"])
        self.assertEqual(out.decision, "codex")
        self.assertTrue(out.overrode_rule)

    def test_forced_cannot_be_overridden(self):
        out, why = validate_gemini({"decision": "claude", "reason": "long enough reason here"},
                                   self.rule("both", forced=True), ["claude", "codex", "both"])
        self.assertIsNone(out)
        self.assertIn("固定ルール", why)

    def test_invalid_choice(self):
        out, why = validate_gemini({"decision": "gpt"}, self.rule(), ["claude", "codex", "both"])
        self.assertIsNone(out)

    def test_extract_json(self):
        self.assertEqual(extract_json('前置き ```json\n{"decision": "both", "reason": "x"}\n``` 後置き')["decision"], "both")
        self.assertEqual(extract_json('{"a": {"b": 1}} trailing')["a"]["b"], 1)
        self.assertIsNone(extract_json("no json here"))

    def test_prompt_contains_numbers(self):
        job = Job("j", "タイトル", "bugfix", "low", "S", "2026-01-01T00:00:00", "仕様本文")
        st = gather_stats(db.connect(Path(tempfile.mkdtemp()) / "x.db"), "bugfix", ["claude", "codex"])
        r = rule_decide(st, "low", ["claude", "codex"], DEFAULT_SETTINGS["dispatch"], DEFAULT_SETTINGS["scoring"])
        p = build_gemini_prompt(job, st, r, ["claude", "codex", "both"])
        self.assertIn('"success_rate"', p)
        self.assertIn("ルール判定", p)
        self.assertIn("仕様本文", p)


if __name__ == "__main__":
    unittest.main()
