"""1回の実行（run）のパイプライン: 作業コピー → エンジン → テスト → パッチ → 禁止語検査 → DB → レポート。"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import db
from .config import Job, load_employee
from .engines import get_engine
from .engines.base import build_prompt
from .sandbox import capture_patch, create_worktree, remove_worktree, run_tests, scan_violations
from .scoring import parse_test_output


@dataclass
class RunReport:
    run_id: int
    job_id: str
    engine: str
    employee: str
    outcome: str
    tests_total: int = 0
    tests_passed: int = 0
    patch_stat: str = ""
    violations: list[str] = field(default_factory=list)
    duration_s: float = 0.0
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost_usd: float | None = None
    run_dir: str = ""
    note: str | None = None


def execute_run(root: Path, settings: dict, companies: dict, conn, job: Job,
                engine_name: str, employee_name: str) -> RunReport:
    crew_cfg = settings["crew"]
    engine = get_engine(engine_name, companies, settings)
    ok, why = engine.available()
    if not ok:
        raise RuntimeError(f"{engine.display_name}（{engine_name}）は使えません: {why}")
    employee = load_employee(root, employee_name)

    revisions = db.count_prior_runs(conn, job.id, engine_name)
    run_id = db.insert_run(conn, job.id, engine_name, employee.name, revisions)
    db.update_job_status(conn, job.id, "running")
    run_dir = root / crew_cfg["runs_dir"] / str(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)

    wt = create_worktree(root, crew_cfg["worktree_dir"], f"run-{run_id}", crew_cfg.get("base_ref", "HEAD"))
    try:
        system_text, user_text = build_prompt(employee, job)
        (run_dir / "prompt.txt").write_text(system_text + "\n\n" + user_text, encoding="utf-8")

        result = engine.run(employee, job, wt, run_dir)
        (run_dir / "engine.log").write_text(result.raw_log or "", encoding="utf-8")
        if result.stderr:
            (run_dir / "stderr.log").write_text(result.stderr, encoding="utf-8")
        (run_dir / "result_message.md").write_text(result.output_text or "", encoding="utf-8")

        test_cmd = job.test_command or str(crew_cfg.get("test_command", "") or "")
        tests_total = tests_passed = 0
        if test_cmd and result.outcome == "success":
            code, out = run_tests(wt, test_cmd, int(crew_cfg.get("test_timeout_s", 600)))
            (run_dir / "tests.log").write_text(f"$ {test_cmd}\nexit={code}\n\n{out}", encoding="utf-8")
            tests_total, tests_passed = parse_test_output(out, code)

        patch, stat = capture_patch(wt)
        patch_path = run_dir / "patch.diff"
        patch_path.write_text(patch, encoding="utf-8")

        violations = scan_violations(result.commands, settings["policy"].get("denylist", []))
        outcome, note = result.outcome, result.error
        if violations:
            outcome, note = "fail", "policy_violation: " + " | ".join(violations)
        elif outcome == "success" and not patch.strip():
            note = "ファイル変更なし（報告のみ）"

        db.finish_run(conn, run_id, outcome=outcome, exit_code=result.exit_code, tests_total=tests_total,
                      tests_passed=tests_passed, duration_s=round(result.duration_s, 2),
                      tokens_in=result.tokens_in, tokens_out=result.tokens_out, cost_usd=result.cost_usd,
                      patch_path=str(patch_path.relative_to(root)), log_path=str((run_dir / "engine.log").relative_to(root)),
                      violations=violations, note=note)
        if outcome == "fail":
            db.insert_review(conn, run_id, "reject", reviewer="system", notes=note)
            db.update_job_status(conn, job.id, "rejected")
        else:
            db.update_job_status(conn, job.id, "awaiting_review")

        rep = RunReport(run_id, job.id, engine_name, employee.name, outcome, tests_total, tests_passed, stat,
                        violations, round(result.duration_s, 2), result.tokens_in, result.tokens_out,
                        result.cost_usd, str(run_dir.relative_to(root)), note)
        (run_dir / "report.md").write_text(render_report(rep, job, engine.display_name, result.output_text), encoding="utf-8")
        return rep
    finally:
        if not crew_cfg.get("keep_worktree", False):
            remove_worktree(root, wt)


def render_report(rep: RunReport, job: Job, company: str, message: str) -> str:
    tests = f"{rep.tests_passed}/{rep.tests_total}" if rep.tests_total else "実行なし"
    tokens = f"in {rep.tokens_in} / out {rep.tokens_out}" if rep.tokens_in is not None else "不明"
    cost = f"${rep.cost_usd:.4f}" if rep.cost_usd is not None else "不明"
    lines = [
        f"# run {rep.run_id} — {job.title}",
        "",
        f"- 案件: {job.id}（{job.category} / risk={job.risk} / {job.complexity}）",
        f"- 会社: {company}（engine={rep.engine}）/ 社員: {rep.employee}",
        f"- 結果: **{rep.outcome}**" + (f" — {rep.note}" if rep.note else ""),
        f"- テスト: {tests}",
        f"- 所要: {rep.duration_s}s / トークン: {tokens} / 費用: {cost}",
        "",
        "## 変更ファイル",
        "```", rep.patch_stat.strip() or "(変更なし)", "```",
        "",
    ]
    if rep.violations:
        lines += ["## 禁止語に該当したコマンド（この run は不採用）", *[f"- {v}" for v in rep.violations], ""]
    lines += ["## エンジンの最終報告", message.strip() or "(なし)", "",
              "## 次の一手（人間）",
              f"- 差分を見る: `cat {rep.run_dir}/patch.diff`",
              f"- 採否: `python3 -m crew review {rep.run_id} --accept` / `--reject --note \"理由\"`",
              f"- 採用後にローカルへ当てる: `python3 -m crew apply {rep.run_id}`（commit / push は人間）", ""]
    return "\n".join(lines)
