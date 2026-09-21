import unittest

from crew.scoring import EngineStats, RuleDecision, parse_test_output, rule_decide, score

SCFG = {"w_success": 0.5, "w_tests": 0.3, "w_revisions": 0.2, "revisions_cap": 3}
DCFG = {"min_samples": 5, "score_margin": 0.10, "force_both_on_high_risk": True, "engines": ["claude", "codex"]}


def st(engine, n, accepts, tt=0, tp=0, rev=0.0):
    return EngineStats(engine, "bugfix", n, accepts, tt, tp, rev)


class ScoreTest(unittest.TestCase):
    def test_formula(self):
        s = st("claude", 10, 8, 20, 19, 0.6)
        self.assertAlmostEqual(score(s, SCFG), 0.5 * 0.8 + 0.3 * 0.95 - 0.2 * 0.2)

    def test_no_tests_uses_success_rate(self):
        s = st("codex", 10, 6)
        self.assertAlmostEqual(score(s, SCFG), 0.5 * 0.6 + 0.3 * 0.6)

    def test_revisions_capped(self):
        s = st("codex", 10, 10, rev=99)
        self.assertAlmostEqual(score(s, SCFG), 0.8 - 0.2)

    def test_empty_stats(self):
        self.assertEqual(score(EngineStats("x"), SCFG), 0.0)


class RuleDecideTest(unittest.TestCase):
    def test_cold_start_is_both(self):
        d = rule_decide({}, "low", ["claude", "codex"], DCFG, SCFG)
        self.assertEqual(d.decision, "both")
        self.assertTrue(d.forced)
        self.assertIn("実績不足", d.reason)

    def test_high_risk_forces_both(self):
        stats = {"claude": st("claude", 20, 20), "codex": st("codex", 20, 2)}
        d = rule_decide(stats, "high", ["claude", "codex"], DCFG, SCFG)
        self.assertEqual(d.decision, "both")
        self.assertTrue(d.forced)

    def test_clear_winner(self):
        stats = {"claude": st("claude", 10, 9, 10, 10, 0.2), "codex": st("codex", 10, 5, 10, 6, 1.5)}
        d = rule_decide(stats, "low", ["claude", "codex"], DCFG, SCFG)
        self.assertEqual(d.decision, "claude")
        self.assertFalse(d.forced)
        self.assertGreater(d.scores["claude"], d.scores["codex"])

    def test_margin_gives_both(self):
        stats = {"claude": st("claude", 10, 8), "codex": st("codex", 10, 8)}
        d = rule_decide(stats, "low", ["claude", "codex"], DCFG, SCFG)
        self.assertEqual(d.decision, "both")
        self.assertFalse(d.forced)

    def test_single_available_engine(self):
        d = rule_decide({}, "high", ["claude"], DCFG, SCFG)
        self.assertEqual(d.decision, "claude")
        self.assertTrue(d.forced)

    def test_no_engine_raises(self):
        with self.assertRaises(RuntimeError):
            rule_decide({}, "low", [], DCFG, SCFG)


class ParseTestOutputTest(unittest.TestCase):
    def test_unittest_ok(self):
        self.assertEqual(parse_test_output("....\nRan 4 tests in 0.01s\n\nOK\n", 0), (4, 4))

    def test_unittest_failed(self):
        out = "Ran 6 tests in 0.1s\n\nFAILED (failures=1, errors=2)\n"
        self.assertEqual(parse_test_output(out, 1), (6, 3))

    def test_pytest(self):
        self.assertEqual(parse_test_output("== 2 failed, 8 passed in 1.2s ==", 1), (10, 8))
        self.assertEqual(parse_test_output("== 8 passed in 1.2s ==", 0), (8, 8))

    def test_jest(self):
        self.assertEqual(parse_test_output("Tests:       1 failed, 9 passed, 10 total", 1), (10, 9))

    def test_fallback_exit_code(self):
        self.assertEqual(parse_test_output("", 0), (1, 1))
        self.assertEqual(parse_test_output("", 3), (1, 0))
        self.assertEqual(parse_test_output("", None), (0, 0))


if __name__ == "__main__":
    unittest.main()
