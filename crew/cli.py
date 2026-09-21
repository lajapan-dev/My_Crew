"""crew コマンド本体。薄く保ち、処理は各モジュールに置く。"""
from __future__ import annotations

import argparse
import os
import platform
import shutil
import sys
from pathlib import Path

from . import __version__, db
from .config import (CATEGORIES, COMPLEXITIES, RISKS, Job, find_root, list_employees, load_companies,
                     load_dotenv, load_settings, new_job_id, now_iso, read_job_file, write_job_file)
from .dispatcher import detect_available, dispatch
from .engines import engine_names
from .engines.gemini_client import gemini_available
from .report import render_html, stats_json, stats_table
from .runner import execute_run
from .sandbox import apply_patch, has_commits, is_git_repo, working_tree_dirty


class Ctx:
    def __init__(self, root: Path):
        self.root = root
        load_dotenv(root)
        self.settings = load_settings(root)
        self.companies = load_companies(root)
        self._conn = None

    @property
    def conn(self):
        if self._conn is None:
            self._conn = db.connect(self.root / self.settings["crew"]["db_path"])
        return self._conn

    def job(self, job_id: str) -> Job:
        job = read_job_file(self.root / self.settings["crew"]["jobs_dir"], job_id)
        row = db.get_job(self.conn, job_id)
        if row is None:
            raise SystemExit(f"案件 {job_id} がDBにありません（jobs/ のファイルはあります）。`crew submit` で作った案件だけ扱えます")
        job.status, job.adopted_run_id = row["status"], row["adopted_run_id"]
        return job


def _p(msg: str = "") -> None:
    print(msg)


# ---------------------------------------------------------------- commands

def cmd_init(ctx: Ctx, a) -> int:
    c = ctx.settings["crew"]
    for d in (c["runs_dir"], c["jobs_dir"], Path(c["db_path"]).parent, c["worktree_dir"]):
        (ctx.root / d).mkdir(parents=True, exist_ok=True)
    ctx.conn  # creates schema
    _p(f"初期化しました: {ctx.root}")
    _p(f"- 実績DB: {c['db_path']}\n- 案件票: {c['jobs_dir']}/\n- 成果物: {c['runs_dir']}/")
    return cmd_doctor(ctx, a)


def cmd_doctor(ctx: Ctx, a) -> int:
    _p(f"crew v{__version__} / Python {platform.python_version()} / root={ctx.root}")
    git_ok = is_git_repo(ctx.root)
    _p(f"[git] {'OK' if git_ok else 'NG: git リポジトリではありません'}"
       + ("" if not git_ok or has_commits(ctx.root) else "（コミットが1つも無いので作業コピーを切れません）"))
    _p("[実行部隊]")
    for e, (ok, why) in detect_available(ctx.companies, ctx.settings).items():
        name = ctx.companies.get(e, {}).get("name", e)
        _p(f"  {'OK' if ok else 'NG'} {name} (engine={e}): {why}")
    _p("  OK 模擬エンジン (engine=mock): 鍵不要で流れを試せる")
    g = ctx.companies.get("gemini", {"command": "gemini"})
    ok, why = gemini_available(g)
    _p(f"[発注本部長] {'OK' if ok else 'NG'} {g.get('name', '発注本部長')} (gemini): {why}")
    keys = [k for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY") if os.environ.get(k)]
    _p(f"[鍵] 読めている環境変数: {', '.join(keys) if keys else 'なし'}（値は表示しない）")
    emps = list_employees(ctx.root)
    _p(f"[社員] {len(emps)}名: {', '.join(e.name for e in emps)}")
    companies = ", ".join(f"{v.get('name')}({k})" for k, v in ctx.companies.items())
    _p(f"[会社] {companies}")
    dbp = ctx.root / ctx.settings["crew"]["db_path"]
    _p(f"[DB] {'あり' if dbp.exists() else '未作成（crew init）'}: {dbp.relative_to(ctx.root)}")
    return 0


def cmd_employees(ctx: Ctx, a) -> int:
    for e in list_employees(ctx.root):
        _p(f"{e.name:<10} {e.description}  [tools: {', '.join(e.tools) or '-'}]")
    return 0


def cmd_submit(ctx: Ctx, a) -> int:
    jobs_dir = ctx.root / ctx.settings["crew"]["jobs_dir"]
    spec = a.spec or ""
    if a.spec_file:
        spec = Path(a.spec_file).read_text(encoding="utf-8")
    job = Job(id=new_job_id(jobs_dir), title=a.title, category=a.category, risk=a.risk,
              complexity=a.complexity, created_at=now_iso(), spec=spec, test_command=a.test_command)
    path = write_job_file(jobs_dir, job)
    db.insert_job(ctx.conn, job)
    _p(f"案件票を作りました: {job.id}\n- {path.relative_to(ctx.root)}（仕様はこのファイルを編集）\n"
       f"- 次: python3 -m crew dispatch {job.id}")
    return 0


def cmd_dispatch(ctx: Ctx, a) -> int:
    job = ctx.job(a.job_id)
    try:
        out = dispatch(ctx.conn, ctx.settings, ctx.companies, job, ctx.root,
                       use_gemini=False if a.no_gemini else None, force=a.force, dry_run=a.dry_run)
    except ValueError as e:
        raise SystemExit(str(e))
    if not a.dry_run:
        db.update_job_status(ctx.conn, job.id, "dispatched")
    _p(f"案件 {job.id}: {job.title}  [{job.category} / risk={job.risk} / {job.complexity}]")
    _p(f"ルール判定: {out.rule.decision}  — {out.rule.reason}")
    _p(f"  スコア: {out.rule.scores}  n: {out.rule.details.get('n')}")
    _p(f"決定: **{out.decision}**  by {out.decided_by}" + (f"（confidence={out.confidence}）" if out.confidence is not None else ""))
    if out.overrode_rule:
        _p(f"  ★ 発注本部長がルールを覆しました: {out.reason}")
    if out.note:
        _p(f"  備考: {out.note}")
    _p("（--dry-run: 記録していません）" if a.dry_run else f"次: python3 -m crew run {job.id}")
    return 0


def cmd_run(ctx: Ctx, a) -> int:
    job = ctx.job(a.job_id)
    if job.status == "done" and not a.force:
        raise SystemExit(f"案件 {job.id} は採用済み（run {job.adopted_run_id}）です。やり直すなら --force")
    if not is_git_repo(ctx.root) or not has_commits(ctx.root):
        raise SystemExit("git リポジトリにコミットが必要です（作業コピーを切るため）")
    employee = a.employee or ctx.settings["crew"]["default_employee"]
    if a.engine:
        choice = a.engine
    else:
        d = db.get_decision(ctx.conn, job.id)
        if d is None:
            raise SystemExit(f"発注先が未決定です。先に `python3 -m crew dispatch {job.id}` を実行するか --engine で指定してください")
        choice = d["decision"]
    engines = ctx.settings["dispatch"].get("engines", ["claude", "codex"]) if choice == "both" else [choice]
    for e in engines:
        if e not in engine_names():
            raise SystemExit(f"未知のエンジン '{e}'。使えるのは: {', '.join(engine_names())} / both")
    if a.dry_run:
        _p(f"[dry-run] 案件 {job.id} を {', '.join(engines)} で実行（社員: {employee}）。作業コピーを切り、パッチとレポートを runs/ に出します")
        return 0
    if working_tree_dirty(ctx.root):
        _p("注意: 未コミットの変更があります。作業コピーは最新コミットから切るため、実行部隊にはその変更が見えません。")
    reports = []
    for e in engines:
        _p(f"▶ {ctx.companies.get(e, {}).get('name', e)} (engine={e}) / 社員 {employee} で実行中…")
        try:
            rep = execute_run(ctx.root, ctx.settings, ctx.companies, ctx.conn, job, e, employee)
        except RuntimeError as ex:
            _p(f"  中止: {ex}")
            continue
        reports.append(rep)
        tests = f"{rep.tests_passed}/{rep.tests_total}" if rep.tests_total else "-"
        _p(f"  run {rep.run_id}: {rep.outcome}  tests={tests}  {rep.duration_s}s  → {rep.run_dir}/report.md"
           + (f"\n  注意: {rep.note}" if rep.note else ""))
    if len(reports) > 1:
        _p("\n比較:")
        _p(f"{'run':>4} {'engine':<8} {'outcome':<8} {'tests':>7} {'sec':>6} {'patch'}")
        for r in reports:
            tests = f"{r.tests_passed}/{r.tests_total}" if r.tests_total else "-"
            last = (r.patch_stat.strip().splitlines() or ["(変更なし)"])[-1].strip()
            _p(f"{r.run_id:>4} {r.engine:<8} {r.outcome:<8} {tests:>7} {r.duration_s:>6} {last}")
        _p("採用は片方だけ: python3 -m crew review <run_id> --accept")
    elif reports:
        _p(f"次: python3 -m crew review {reports[0].run_id} --accept | --reject --note \"理由\"")
    return 0 if reports and all(r.outcome == "success" for r in reports) else 1


def cmd_review(ctx: Ctx, a) -> int:
    run = db.get_run(ctx.conn, a.run_id)
    if run is None:
        raise SystemExit(f"run {a.run_id} がありません")
    jobrow = db.get_job(ctx.conn, run["job_id"])
    verdict = "accept" if a.accept else "reject"
    if verdict == "accept":
        if run["outcome"] != "success":
            raise SystemExit(f"run {a.run_id} は {run['outcome']} なので採用できません")
        if jobrow["adopted_run_id"] and jobrow["adopted_run_id"] != a.run_id and not a.force:
            raise SystemExit(f"案件 {run['job_id']} は既に run {jobrow['adopted_run_id']} を採用済みです（採用は片方だけ）。変えるなら --force")
    db.insert_review(ctx.conn, a.run_id, verdict, "human", a.note)
    if verdict == "accept":
        db.update_job_status(ctx.conn, run["job_id"], "done", a.run_id)
        _p(f"run {a.run_id} を採用しました。案件 {run['job_id']} は done。\n次: python3 -m crew apply {a.run_id}")
    else:
        if not jobrow["adopted_run_id"]:
            db.update_job_status(ctx.conn, run["job_id"], "rejected")
        _p(f"run {a.run_id} を差し戻しました。再実行: python3 -m crew run {run['job_id']} --engine {run['engine']}")
    return 0


def cmd_apply(ctx: Ctx, a) -> int:
    run = db.get_run(ctx.conn, a.run_id)
    if run is None:
        raise SystemExit(f"run {a.run_id} がありません")
    rows = db.list_runs(ctx.conn, run["job_id"])
    verdict = next((r["verdict"] for r in rows if r["id"] == a.run_id), None)
    if verdict != "accept":
        raise SystemExit(f"run {a.run_id} は採用されていません（review --accept が先）")
    patch = ctx.root / (run["patch_path"] or "")
    if not run["patch_path"] or not patch.exists() or not patch.read_text(encoding="utf-8").strip():
        raise SystemExit("当てるパッチがありません（変更なしの run）")
    if working_tree_dirty(ctx.root) and not a.allow_dirty:
        raise SystemExit("作業ツリーに未コミットの変更があります。先に片付けるか --allow-dirty")
    ok, msg = apply_patch(ctx.root, patch, check_only=True)
    if not ok:
        raise SystemExit(f"パッチが当たりません（ベースが変わった可能性）:\n{msg}")
    ok, msg = apply_patch(ctx.root, patch)
    if not ok:
        raise SystemExit(f"適用失敗:\n{msg}")
    _p(f"run {a.run_id} のパッチをローカルに当てました。git diff で確認し、commit / push は人間が行ってください。")
    return 0


def cmd_stats(ctx: Ctx, a) -> int:
    if a.json:
        _p(stats_json(ctx.conn, ctx.settings["scoring"], a.category))
        return 0
    _p(stats_table(ctx.conn, ctx.settings["scoring"], a.category))
    if a.html:
        out = ctx.root / ctx.settings["crew"]["runs_dir"] / "dashboard.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render_html(ctx.conn, ctx.settings), encoding="utf-8")
        _p(f"\nダッシュボード: {out.relative_to(ctx.root)}（ブラウザで開く）")
    return 0


def cmd_list(ctx: Ctx, a) -> int:
    if a.what == "runs":
        rows = db.list_runs(ctx.conn, a.job)
        _p(f"{'run':>4} {'job':<13} {'engine':<7} {'employee':<9} {'outcome':<8} {'verdict':<7} {'tests':>6} {'started'}")
        for r in rows:
            tests = f"{r['tests_passed']}/{r['tests_total']}" if r["tests_total"] else "-"
            _p(f"{r['id']:>4} {r['job_id']:<13} {r['engine']:<7} {r['employee']:<9} {r['outcome']:<8} {r['verdict'] or '':<7} {tests:>6} {r['started_at']}")
        return 0
    rows = db.list_jobs(ctx.conn)
    _p(f"{'job':<13} {'status':<15} {'cat':<9} {'risk':<6} {'decision':<8} {'runs':>4}  title")
    for r in rows:
        _p(f"{r['id']:<13} {r['status']:<15} {r['category']:<9} {r['risk']:<6} {r['decision'] or '-':<8} {r['run_count']:>4}  {r['title']}")
    return 0


# ---------------------------------------------------------------- parser

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="crew", description="AI社員組織 CLI（Claude Code株式会社 / Codex株式会社 / 発注本部長）")
    p.add_argument("--root", help="crew.toml のある場所（既定: 自動検出）")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="DB とフォルダを作る").set_defaults(fn=cmd_init)
    sub.add_parser("doctor", help="CLI・鍵・git の状態確認").set_defaults(fn=cmd_doctor)
    sub.add_parser("employees", help="社員一覧").set_defaults(fn=cmd_employees)

    s = sub.add_parser("submit", help="案件票を作る")
    s.add_argument("title")
    s.add_argument("--category", choices=CATEGORIES, default="other")
    s.add_argument("--risk", choices=RISKS, default="medium")
    s.add_argument("--complexity", choices=COMPLEXITIES, default="M")
    s.add_argument("--spec", help="仕様（短文）")
    s.add_argument("--spec-file", help="仕様ファイル")
    s.add_argument("--test-command", help="この案件だけのテストコマンド")
    s.set_defaults(fn=cmd_submit)

    s = sub.add_parser("dispatch", help="発注先を決める")
    s.add_argument("job_id")
    s.add_argument("--dry-run", action="store_true", help="判断だけ表示して記録しない")
    s.add_argument("--no-gemini", action="store_true", help="発注本部長を呼ばずルール判定のみ")
    s.add_argument("--force", action="store_true", help="既存の発注記録を上書き")
    s.set_defaults(fn=cmd_dispatch)

    s = sub.add_parser("run", help="実行してパッチとレポートを出す")
    s.add_argument("job_id")
    s.add_argument("--engine", help="claude / codex / both / mock（省略時は発注決定どおり）")
    s.add_argument("--employee", help="社員名（既定: crew.toml の default_employee）")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--force", action="store_true", help="採用済み案件でも実行")
    s.set_defaults(fn=cmd_run)

    s = sub.add_parser("review", help="人間の採否")
    s.add_argument("run_id", type=int)
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--accept", action="store_true")
    g.add_argument("--reject", action="store_true")
    s.add_argument("--note")
    s.add_argument("--force", action="store_true", help="採用済みを差し替える")
    s.set_defaults(fn=cmd_review)

    s = sub.add_parser("apply", help="採用パッチをローカルに当てる（commit / push は人間）")
    s.add_argument("run_id", type=int)
    s.add_argument("--allow-dirty", action="store_true")
    s.set_defaults(fn=cmd_apply)

    s = sub.add_parser("stats", help="エンジン別成績表")
    s.add_argument("--category", choices=CATEGORIES)
    s.add_argument("--html", action="store_true", help="runs/dashboard.html を生成")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_stats)

    s = sub.add_parser("list", help="案件 / 実行の一覧")
    s.add_argument("what", nargs="?", choices=("jobs", "runs"), default="jobs")
    s.add_argument("--job", help="runs を案件で絞る")
    s.set_defaults(fn=cmd_list)
    return p


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    root = Path(a.root).resolve() if a.root else find_root()
    if not (root / "crew.toml").exists():
        print(f"crew.toml が見つかりません（{root}）。リポジトリ直下で実行するか --root を指定してください", file=sys.stderr)
        return 2
    ctx = Ctx(root)
    try:
        return int(a.fn(ctx, a) or 0)
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        return 2
    finally:
        if ctx._conn is not None:
            ctx._conn.close()
