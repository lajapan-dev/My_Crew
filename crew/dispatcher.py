"""発注本部長。ルール判定（数値）→ 必要なときだけ Gemini に最終判断を仰ぐ。"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .config import Job
from .db import engine_stats, upsert_decision
from .engines import get_engine
from .engines.gemini_client import ask_gemini, extract_json, gemini_available
from .scoring import EngineStats, RuleDecision, rule_decide


@dataclass
class DispatchOutcome:
    decision: str
    decided_by: str          # 'rule' | 'gemini'
    reason: str
    rule: RuleDecision
    overrode_rule: bool = False
    confidence: float | None = None
    note: str = ""           # Gemini を呼ばなかった／却下した理由など


def detect_available(companies: dict, settings: dict) -> dict[str, tuple[bool, str]]:
    out = {}
    for e in settings["dispatch"].get("engines", ["claude", "codex"]):
        try:
            out[e] = get_engine(e, companies, settings).available()
        except KeyError as ex:
            out[e] = (False, str(ex))
    return out


def gather_stats(conn, category: str | None, engines: list[str]) -> dict[str, EngineStats]:
    rows = engine_stats(conn, category)
    return {e: EngineStats.from_rows(rows, e, category or "*") for e in engines}


def stats_summary(stats: dict[str, EngineStats], rule: RuleDecision) -> dict:
    out = {}
    for e, st in stats.items():
        out[e] = {
            "n": st.n, "success_rate": round(st.success_rate, 3),
            "test_pass_rate": None if st.test_pass_rate is None else round(st.test_pass_rate, 3),
            "avg_revisions": round(st.avg_revisions, 2), "score": rule.scores.get(e),
        }
    return out


def build_gemini_prompt(job: Job, stats: dict[str, EngineStats], rule: RuleDecision, choices: list[str]) -> str:
    spec = " ".join(job.spec.split())[:400]
    return (
        "あなたはAI社員組織の「発注本部長」です。案件を claude（Claude Code株式会社）/ codex（Codex株式会社）/ both（両社に出して比較）"
        "のどこに発注するか決めます。\n"
        "判断は必ず下記の実績数値に基づきます。ルール判定と異なる決定をする場合は、reason に数値上の根拠を必ず書いてください。"
        "根拠が書けなければルール判定に従ってください。雰囲気や一般論で決めてはいけません。\n"
        "出力は JSON のみ（前後に文章を付けない）: "
        '{"decision": "claude|codex|both", "confidence": 0.0〜1.0, "reason": "…"}\n\n'
        f"【案件】{job.id} {job.title}\n種別={job.category} リスク={job.risk} 複雑さ={job.complexity}\n仕様: {spec}\n\n"
        f"【実績（category={job.category}、n=採否が付いた件数）】\n{json.dumps(stats_summary(stats, rule), ensure_ascii=False)}\n\n"
        f"【ルール判定】decision={rule.decision} / 理由: {rule.reason}\n"
        f"【選べる値】{' / '.join(choices)}\n"
    )


def validate_gemini(parsed: dict | None, rule: RuleDecision, choices: list[str]) -> tuple[DispatchOutcome | None, str]:
    """Gemini の回答を検証する。使えなければ (None, 理由)。"""
    if not parsed:
        return None, "JSON を読み取れなかった"
    decision = str(parsed.get("decision", "")).strip().lower()
    reason = str(parsed.get("reason", "")).strip()
    try:
        conf = float(parsed.get("confidence")) if parsed.get("confidence") is not None else None
        conf = None if conf is None else max(0.0, min(1.0, conf))
    except (TypeError, ValueError):
        conf = None
    if decision not in choices:
        return None, f"選べない値 '{decision}'"
    if decision != rule.decision:
        if rule.forced:
            return None, f"固定ルール（{rule.reason}）は覆せない。Gemini案 '{decision}' を却下"
        if len(reason) < 10:
            return None, "ルールと異なる決定なのに理由が無い。却下"
        return DispatchOutcome(decision, "gemini", reason, rule, True, conf), ""
    return DispatchOutcome(decision, "gemini", reason or rule.reason, rule, False, conf), ""


def decide(conn, settings: dict, companies: dict, job: Job, root: Path,
           available: list[str] | None = None, use_gemini: bool | None = None) -> DispatchOutcome:
    dcfg, scfg = settings["dispatch"], settings["scoring"]
    if available is None:
        available = [e for e, (ok, _) in detect_available(companies, settings).items() if ok]
    engines = [e for e in dcfg.get("engines", ["claude", "codex"])]
    stats = gather_stats(conn, job.category, engines)
    rule = rule_decide(stats, job.risk, available, dcfg, scfg)
    use_gemini = dcfg.get("use_gemini", True) if use_gemini is None else use_gemini
    outcome = DispatchOutcome(rule.decision, "rule", rule.reason, rule)

    if not use_gemini:
        outcome.note = "発注本部長（gemini）は無効化されているためルール判定"
        return outcome
    if rule.forced:
        outcome.note = "固定ルールで決まるため発注本部長は呼ばない（無料枠の節約）"
        return outcome
    gcfg = companies.get("gemini", {"engine": "gemini", "command": "gemini"})
    ok, why = gemini_available(gcfg)
    if not ok:
        outcome.note = f"発注本部長を呼べないためルール判定: {why}"
        return outcome
    choices = [e for e in engines if e in available] + ["both"]
    text, raw = ask_gemini(gcfg, build_gemini_prompt(job, stats, rule, choices), root)
    if text is None:
        outcome.note = f"発注本部長の応答なし → ルール判定: {raw[:200]}"
        return outcome
    result, why = validate_gemini(extract_json(text), rule, choices)
    if result is None:
        outcome.note = f"発注本部長の回答を却下 → ルール判定: {why}"
        return outcome
    result.note = "発注本部長（gemini）が決定"
    return result


def dispatch(conn, settings: dict, companies: dict, job: Job, root: Path,
             available: list[str] | None = None, use_gemini: bool | None = None,
             force: bool = False, dry_run: bool = False) -> DispatchOutcome:
    out = decide(conn, settings, companies, job, root, available, use_gemini)
    if not dry_run:
        upsert_decision(conn, job.id, out.decided_by, out.decision, out.rule.decision,
                        {"scores": out.rule.scores, **out.rule.details}, out.reason, out.overrode_rule,
                        out.confidence, force=force)
    return out
