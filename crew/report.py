"""成績表（テキスト）とダッシュボード（静的HTML 1枚）。"""
from __future__ import annotations

import html
import json
from datetime import datetime

from .db import engine_stats, list_decisions, list_runs
from .scoring import EngineStats, score


def _rows(conn, scoring_cfg: dict, category: str | None = None) -> list[dict]:
    out = []
    for r in engine_stats(conn, category):
        st = EngineStats(r["engine"], r["category"], int(r["reviewed"] or 0), int(r["accepts"] or 0),
                         int(r["tests_total"] or 0), int(r["tests_passed"] or 0), float(r["avg_revisions"] or 0))
        out.append(_row_from_stats(st, int(r["runs"] or 0), float(r["avg_duration_s"] or 0),
                                   float(r["cost_usd"] or 0), scoring_cfg))
    return out


def _row_from_stats(st: EngineStats, runs: int, avg_duration_s: float, cost_usd: float, scoring_cfg: dict) -> dict:
    return {
        "engine": st.engine, "category": st.category, "runs": runs, "n": st.n,
        "accepts": st.accepts, "tests_total": st.tests_total, "tests_passed": st.tests_passed,
        "success_rate": st.success_rate, "test_pass_rate": st.test_pass_rate,
        "avg_revisions": st.avg_revisions, "score": score(st, scoring_cfg),
        "avg_duration_s": avg_duration_s, "cost_usd": cost_usd,
    }


def _overall(rows: list[dict], scoring_cfg: dict) -> list[dict]:
    """エンジン別（全カテゴリ合算）。"""
    out = []
    for e in sorted({r["engine"] for r in rows}):
        mine = [r for r in rows if r["engine"] == e]
        runs = sum(r["runs"] for r in mine)
        st = EngineStats(e, "*", sum(r["n"] for r in mine), sum(r["accepts"] for r in mine),
                         sum(r["tests_total"] for r in mine), sum(r["tests_passed"] for r in mine),
                         (sum(r["avg_revisions"] * r["runs"] for r in mine) / runs) if runs else 0.0)
        dur = (sum(r["avg_duration_s"] * r["runs"] for r in mine) / runs) if runs else 0.0
        out.append(_row_from_stats(st, runs, dur, sum(r["cost_usd"] for r in mine), scoring_cfg))
    return out


def _fmt_rate(v) -> str:
    return "-" if v is None else f"{v:.0%}"


def stats_table(conn, scoring_cfg: dict, category: str | None = None) -> str:
    rows = _rows(conn, scoring_cfg, category)
    if not rows:
        return "まだ実績がありません。`crew run` → `crew review` で貯まります。"
    head = f"{'engine':<8} {'category':<10} {'runs':>4} {'n':>3} {'success':>8} {'tests':>6} {'avg_rev':>7} {'score':>6} {'cost$':>7}"
    lines = [head, "-" * len(head)]
    for r in rows:
        lines.append(f"{r['engine']:<8} {r['category']:<10} {r['runs']:>4} {r['n']:>3} {_fmt_rate(r['success_rate']):>8} "
                     f"{_fmt_rate(r['test_pass_rate']):>6} {r['avg_revisions']:>7.2f} {r['score']:>6.3f} {r['cost_usd']:>7.2f}")
    lines.append("")
    lines.append("n = 採否が付いた run 数。success = accept 率。tests = テスト通過率（無ければ -）。")
    lines.append("score = 0.5×success + 0.3×tests(無ければ success) − 0.2×min(avg_rev/3, 1)")
    return "\n".join(lines)


def stats_json(conn, scoring_cfg: dict, category: str | None = None) -> str:
    return json.dumps(_rows(conn, scoring_cfg, category), ensure_ascii=False, indent=2)


_CSS = """
:root{--bg:#fff;--fg:#1a1a1a;--muted:#666;--line:#ddd;--ok:#1a7f37;--ng:#c62828;--head:#f4f4f4}
@media (prefers-color-scheme:dark){:root{--bg:#121212;--fg:#eaeaea;--muted:#aaa;--line:#333;--ok:#4caf50;--ng:#ef5350;--head:#1e1e1e}}
body{margin:0;padding:16px;background:var(--bg);color:var(--fg);font:14px/1.5 -apple-system,"Hiragino Sans","Noto Sans JP",sans-serif}
main{max-width:1100px;margin:0 auto}h1{font-size:20px;margin:0 0 4px}h2{font-size:16px;margin:24px 0 8px}
.sub{color:var(--muted);margin:0 0 16px}table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}
th,td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}th{background:var(--head)}
td.num,th.num{text-align:right}.ok{color:var(--ok);font-weight:600}.ng{color:var(--ng);font-weight:600}
.wrap{overflow-x:auto}small{color:var(--muted)}
"""


def _table(headers: list[tuple[str, bool]], rows: list[list[str]]) -> str:
    th = "".join(f'<th class="{"num" if n else ""}">{html.escape(h)}</th>' for h, n in headers)
    body = []
    for r in rows:
        tds = []
        for (h, n), v in zip(headers, r):
            cls = "num" if n else ""
            if v in ("success", "accept"):
                cls += " ok"
            elif v in ("fail", "reject"):
                cls += " ng"
            tds.append(f'<td class="{cls.strip()}">{html.escape(str(v))}</td>')
        body.append("<tr>" + "".join(tds) + "</tr>")
    return f'<div class="wrap"><table><thead><tr>{th}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'


def render_html(conn, settings: dict) -> str:
    scfg = settings["scoring"]
    rows = _rows(conn, scfg)
    overall = _overall(rows, scfg)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    parts = [f"<!doctype html><html lang=ja><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
             f"<title>Crew Dashboard</title><style>{_CSS}</style></head><body><main>",
             "<h1>AI社員組織 成績表</h1>",
             f"<p class=sub>生成 {now} ／ score = 0.5×success + 0.3×tests − 0.2×min(avg_rev/3,1)</p>"]

    hdr = [("engine", False), ("category", False), ("runs", True), ("n", True), ("success", True),
           ("tests", True), ("avg_rev", True), ("score", True), ("cost $", True)]
    fmt = lambda r: [r["engine"], r["category"], r["runs"], r["n"], _fmt_rate(r["success_rate"]),
                     _fmt_rate(r["test_pass_rate"]), f"{r['avg_revisions']:.2f}", f"{r['score']:.3f}", f"{r['cost_usd']:.2f}"]
    parts.append("<h2>エンジン別（全カテゴリ）</h2>")
    parts.append(_table(hdr, [fmt(r) for r in overall]) if overall else "<p><small>実績なし</small></p>")
    parts.append("<h2>エンジン × カテゴリ</h2>")
    parts.append(_table(hdr, [fmt(r) for r in rows]) if rows else "<p><small>実績なし</small></p>")

    decs = list_decisions(conn, 30)
    parts.append("<h2>直近の発注判断</h2>")
    parts.append(_table([("job", False), ("title", False), ("category", False), ("risk", False), ("decision", False),
                         ("by", False), ("override", False), ("reason", False)],
                        [[d["job_id"], d["title"], d["category"], d["risk"], d["decision"], d["decided_by"],
                          "★" if d["overrode_rule"] else "", d["reason"]] for d in decs])
                 if decs else "<p><small>まだ発注していません</small></p>")

    runs = list_runs(conn, None, 50)
    parts.append("<h2>直近の実行</h2>")
    parts.append(_table([("run", True), ("job", False), ("engine", False), ("employee", False), ("outcome", False),
                         ("verdict", False), ("tests", True), ("rev", True), ("sec", True), ("note", False)],
                        [[r["id"], r["job_id"], r["engine"], r["employee"], r["outcome"], r["verdict"] or "",
                          f"{r['tests_passed']}/{r['tests_total']}" if r["tests_total"] else "-", r["revisions"],
                          f"{r['duration_s'] or 0:.0f}", (r["note"] or "")[:80]] for r in runs])
                 if runs else "<p><small>まだ実行していません</small></p>")
    parts.append("</main></body></html>")
    return "\n".join(parts)
