"""スコア式とルール判定。純粋関数のみ（DBや外部プロセスに触らない）。"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class EngineStats:
    engine: str
    category: str = "*"
    reviewed: int = 0        # 人間（または system）が採否を付けた run 数 = 標本数 n
    accepts: int = 0
    tests_total: int = 0
    tests_passed: int = 0
    avg_revisions: float = 0.0

    @property
    def n(self) -> int:
        return self.reviewed

    @property
    def success_rate(self) -> float:
        return self.accepts / self.reviewed if self.reviewed else 0.0

    @property
    def test_pass_rate(self) -> float | None:
        return self.tests_passed / self.tests_total if self.tests_total else None

    @classmethod
    def from_rows(cls, rows: list[dict], engine: str, category: str = "*") -> "EngineStats":
        """engine_stats() の行（複数カテゴリ可）を1エンジン分に合算する。"""
        st = cls(engine=engine, category=category)
        mine = [r for r in rows if r["engine"] == engine]
        total_runs = sum(int(r["runs"] or 0) for r in mine)
        weighted = 0.0
        for r in mine:
            st.reviewed += int(r["reviewed"] or 0)
            st.accepts += int(r["accepts"] or 0)
            st.tests_total += int(r["tests_total"] or 0)
            st.tests_passed += int(r["tests_passed"] or 0)
            weighted += float(r["avg_revisions"] or 0) * int(r["runs"] or 0)
        st.avg_revisions = weighted / total_runs if total_runs else 0.0
        return st


def score(st: EngineStats, cfg: dict) -> float:
    """score = w_success×成功率 + w_tests×テスト通過率 − w_revisions×min(平均修正/cap, 1)"""
    tpr = st.test_pass_rate
    if tpr is None:
        tpr = st.success_rate  # テスト実績が無ければ成功率で代用
    cap = float(cfg.get("revisions_cap", 3)) or 3.0
    return (float(cfg.get("w_success", 0.5)) * st.success_rate
            + float(cfg.get("w_tests", 0.3)) * tpr
            - float(cfg.get("w_revisions", 0.2)) * min(st.avg_revisions / cap, 1.0))


@dataclass
class RuleDecision:
    decision: str                 # 'claude' | 'codex' | 'both' | 単独エンジン名
    reason: str
    forced: bool                  # True なら発注本部長も覆せない
    scores: dict = field(default_factory=dict)
    details: dict = field(default_factory=dict)


def rule_decide(stats: dict[str, EngineStats], risk: str, available: list[str], cfg: dict,
                scoring_cfg: dict) -> RuleDecision:
    """数値だけで発注先を決める。stats はエンジン名→EngineStats（無いエンジンは n=0 扱い）。"""
    engines = [e for e in cfg.get("engines", ["claude", "codex"]) if e in available]
    if not engines:
        raise RuntimeError("利用可能な実行エンジンがありません（doctor で確認してください）")
    min_n = int(cfg.get("min_samples", 5))
    margin = float(cfg.get("score_margin", 0.10))
    sc = {e: round(score(stats.get(e, EngineStats(e)), scoring_cfg), 4) for e in engines}
    ns = {e: stats.get(e, EngineStats(e)).n for e in engines}
    details = {"n": ns, "min_samples": min_n, "margin": margin, "available": engines}

    if len(engines) == 1:
        return RuleDecision(engines[0], f"利用可能なエンジンが {engines[0]} のみ", True, sc, details)
    if risk == "high" and cfg.get("force_both_on_high_risk", True):
        return RuleDecision("both", "risk=high のため両社比較（固定ルール）", True, sc, details)
    lacking = [e for e in engines if ns[e] < min_n]
    if lacking:
        return RuleDecision("both", f"実績不足（{', '.join(f'{e}: n={ns[e]}' for e in lacking)} < {min_n}）のため両社比較でデータを貯める",
                            True, sc, details)
    ranked = sorted(engines, key=lambda e: sc[e], reverse=True)
    best, second = ranked[0], ranked[1]
    gap = sc[best] - sc[second]
    if gap < margin:
        return RuleDecision("both", f"スコア差 {gap:.3f} < {margin} のため両社比較", False, sc, details)
    return RuleDecision(best, f"{best} のスコア {sc[best]:.3f} が {second} の {sc[second]:.3f} を {gap:.3f} 上回る",
                        False, sc, details)


# ---------------------------------------------------------------- test output

_PYTEST = re.compile(r"(?:(\d+) failed)?(?:, )?(?:(\d+) passed)?", re.I)


def parse_test_output(text: str, exit_code: int | None) -> tuple[int, int]:
    """テスト出力から (total, passed) を推定する。分からなければ終了コードで 1件扱い。"""
    t = text or ""
    # unittest: "Ran 12 tests" + "OK" / "FAILED (failures=1, errors=2)"
    m = re.search(r"Ran (\d+) tests?", t)
    if m:
        total = int(m.group(1))
        if total == 0:
            return 0, 0
        bad = 0
        mf = re.search(r"FAILED \(([^)]*)\)", t)
        if mf:
            for part in mf.group(1).split(","):
                k, _, v = part.strip().partition("=")
                if k in ("failures", "errors") and v.isdigit():
                    bad += int(v)
        elif not re.search(r"^OK\b", t, re.M):
            bad = total if (exit_code or 0) != 0 else 0
        return total, max(total - bad, 0)
    # pytest: "3 failed, 10 passed in 1.2s" / "10 passed"
    mp = re.search(r"(\d+) passed", t)
    mf = re.search(r"(\d+) failed", t)
    me = re.search(r"(\d+) errors?\b", t)
    if mp or mf:
        passed = int(mp.group(1)) if mp else 0
        failed = (int(mf.group(1)) if mf else 0) + (int(me.group(1)) if me else 0)
        return passed + failed, passed
    if re.search(r"no tests ran", t, re.I):
        return 0, 0
    # jest: "Tests:       1 failed, 9 passed, 10 total"
    mj = re.search(r"Tests:\s+(?:(\d+) failed, )?(?:(\d+) skipped, )?(\d+) passed, (\d+) total", t)
    if mj:
        return int(mj.group(4)), int(mj.group(3))
    if exit_code is None:
        return 0, 0
    return (1, 1) if exit_code == 0 else (1, 0)
