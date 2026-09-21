"""実績DB（SQLite）。2社共通の成績表。スキーマはここが正本。"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .config import Job, now_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  category TEXT NOT NULL,
  risk TEXT NOT NULL,
  complexity TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open',
  adopted_run_id INTEGER,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dispatch_decisions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT NOT NULL UNIQUE REFERENCES jobs(id),
  decided_by TEXT NOT NULL,            -- 'rule' | 'gemini'
  decision TEXT NOT NULL,              -- 'claude' | 'codex' | 'both'
  rule_decision TEXT NOT NULL,
  rule_scores_json TEXT NOT NULL,
  reason TEXT NOT NULL,
  overrode_rule INTEGER NOT NULL DEFAULT 0,
  confidence REAL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT NOT NULL REFERENCES jobs(id),
  engine TEXT NOT NULL,
  employee TEXT NOT NULL,
  outcome TEXT NOT NULL,               -- 'success' | 'fail' | 'running'
  exit_code INTEGER,
  tests_total INTEGER NOT NULL DEFAULT 0,
  tests_passed INTEGER NOT NULL DEFAULT 0,
  revisions INTEGER NOT NULL DEFAULT 0, -- 同じ案件・同じエンジンでの何回目のやり直しか
  duration_s REAL,
  tokens_in INTEGER,
  tokens_out INTEGER,
  cost_usd REAL,
  patch_path TEXT,
  log_path TEXT,
  violations_json TEXT,
  note TEXT,
  started_at TEXT NOT NULL,
  finished_at TEXT
);
CREATE TABLE IF NOT EXISTS reviews (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL REFERENCES runs(id),
  verdict TEXT NOT NULL,               -- 'accept' | 'reject'
  reviewer TEXT NOT NULL DEFAULT 'human',
  notes TEXT,
  created_at TEXT NOT NULL
);
"""


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


# ---------------------------------------------------------------- jobs

def insert_job(conn: sqlite3.Connection, job: Job) -> None:
    conn.execute(
        "INSERT INTO jobs (id,title,category,risk,complexity,status,created_at,updated_at)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (job.id, job.title, job.category, job.risk, job.complexity, job.status,
         job.created_at or now_iso(), now_iso()),
    )
    conn.commit()


def get_job(conn: sqlite3.Connection, job_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()


def list_jobs(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT j.*, d.decision, d.decided_by,"
        " (SELECT COUNT(*) FROM runs r WHERE r.job_id=j.id) AS run_count"
        " FROM jobs j LEFT JOIN dispatch_decisions d ON d.job_id=j.id ORDER BY j.id"
    ).fetchall()


def update_job_status(conn: sqlite3.Connection, job_id: str, status: str,
                      adopted_run_id: int | None = None) -> None:
    if adopted_run_id is None:
        conn.execute("UPDATE jobs SET status=?, updated_at=? WHERE id=?", (status, now_iso(), job_id))
    else:
        conn.execute("UPDATE jobs SET status=?, adopted_run_id=?, updated_at=? WHERE id=?",
                     (status, adopted_run_id, now_iso(), job_id))
    conn.commit()


# ---------------------------------------------------------------- decisions

def upsert_decision(conn: sqlite3.Connection, job_id: str, decided_by: str, decision: str,
                    rule_decision: str, rule_scores: dict, reason: str, overrode_rule: bool,
                    confidence: float | None, force: bool = False) -> None:
    exists = conn.execute("SELECT 1 FROM dispatch_decisions WHERE job_id=?", (job_id,)).fetchone()
    if exists and not force:
        raise ValueError(f"案件 {job_id} には既に発注記録があります（二重発注防止）。やり直すなら --force")
    if exists:
        conn.execute("DELETE FROM dispatch_decisions WHERE job_id=?", (job_id,))
    conn.execute(
        "INSERT INTO dispatch_decisions (job_id,decided_by,decision,rule_decision,rule_scores_json,"
        "reason,overrode_rule,confidence,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (job_id, decided_by, decision, rule_decision, json.dumps(rule_scores, ensure_ascii=False),
         reason, 1 if overrode_rule else 0, confidence, now_iso()),
    )
    conn.commit()


def get_decision(conn: sqlite3.Connection, job_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM dispatch_decisions WHERE job_id=?", (job_id,)).fetchone()


def list_decisions(conn: sqlite3.Connection, limit: int = 50) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT d.*, j.title, j.category, j.risk FROM dispatch_decisions d JOIN jobs j ON j.id=d.job_id"
        " ORDER BY d.id DESC LIMIT ?", (limit,)).fetchall()


# ---------------------------------------------------------------- runs

def count_prior_runs(conn: sqlite3.Connection, job_id: str, engine: str) -> int:
    row = conn.execute("SELECT COUNT(*) AS c FROM runs WHERE job_id=? AND engine=?", (job_id, engine)).fetchone()
    return int(row["c"])


def insert_run(conn: sqlite3.Connection, job_id: str, engine: str, employee: str, revisions: int) -> int:
    cur = conn.execute(
        "INSERT INTO runs (job_id,engine,employee,outcome,revisions,started_at) VALUES (?,?,?,'running',?,?)",
        (job_id, engine, employee, revisions, now_iso()))
    conn.commit()
    return int(cur.lastrowid)


def finish_run(conn: sqlite3.Connection, run_id: int, **fields) -> None:
    fields["finished_at"] = now_iso()
    if "violations" in fields:
        fields["violations_json"] = json.dumps(fields.pop("violations"), ensure_ascii=False)
    cols = ", ".join(f"{k}=?" for k in fields)
    conn.execute(f"UPDATE runs SET {cols} WHERE id=?", (*fields.values(), run_id))
    conn.commit()


def get_run(conn: sqlite3.Connection, run_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()


def list_runs(conn: sqlite3.Connection, job_id: str | None = None, limit: int = 100) -> list[sqlite3.Row]:
    sql = ("SELECT r.*, j.title, j.category,"
           " (SELECT verdict FROM reviews v WHERE v.run_id=r.id ORDER BY v.id DESC LIMIT 1) AS verdict"
           " FROM runs r JOIN jobs j ON j.id=r.job_id")
    args: tuple = ()
    if job_id:
        sql += " WHERE r.job_id=?"
        args = (job_id,)
    sql += " ORDER BY r.id DESC LIMIT ?"
    return conn.execute(sql, (*args, limit)).fetchall()


# ---------------------------------------------------------------- reviews

def insert_review(conn: sqlite3.Connection, run_id: int, verdict: str, reviewer: str = "human",
                  notes: str | None = None) -> int:
    if verdict not in ("accept", "reject"):
        raise ValueError("verdict は accept / reject のどちらか")
    cur = conn.execute("INSERT INTO reviews (run_id,verdict,reviewer,notes,created_at) VALUES (?,?,?,?,?)",
                       (run_id, verdict, reviewer, notes, now_iso()))
    conn.commit()
    return int(cur.lastrowid)


# ---------------------------------------------------------------- stats

STATS_SQL = """
SELECT r.engine AS engine, j.category AS category,
       COUNT(*) AS runs,
       SUM(CASE WHEN rv.verdict IS NOT NULL THEN 1 ELSE 0 END) AS reviewed,
       SUM(CASE WHEN rv.verdict='accept' THEN 1 ELSE 0 END) AS accepts,
       COALESCE(SUM(r.tests_total),0) AS tests_total,
       COALESCE(SUM(r.tests_passed),0) AS tests_passed,
       COALESCE(AVG(r.revisions),0) AS avg_revisions,
       COALESCE(AVG(r.duration_s),0) AS avg_duration_s,
       COALESCE(SUM(r.cost_usd),0) AS cost_usd
FROM runs r
JOIN jobs j ON j.id = r.job_id
LEFT JOIN (
  SELECT run_id, verdict FROM reviews
  WHERE id IN (SELECT MAX(id) FROM reviews GROUP BY run_id)
) rv ON rv.run_id = r.id
WHERE r.outcome != 'running' AND (? IS NULL OR j.category = ?)
GROUP BY r.engine, j.category
ORDER BY r.engine, j.category
"""


def engine_stats(conn: sqlite3.Connection, category: str | None = None) -> list[dict]:
    rows = conn.execute(STATS_SQL, (category, category)).fetchall()
    return [dict(r) for r in rows]
