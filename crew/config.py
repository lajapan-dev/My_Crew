"""設定・社員定義・案件票の読み書き。外部ライブラリは使わない。"""
from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

CATEGORIES = ("bugfix", "feature", "refactor", "test", "docs", "research", "other")
RISKS = ("low", "medium", "high")
COMPLEXITIES = ("S", "M", "L")

DEFAULT_SETTINGS: dict = {
    "crew": {
        "base_ref": "HEAD",
        "worktree_dir": ".worktrees",
        "runs_dir": "runs",
        "jobs_dir": "jobs",
        "db_path": "data/crew.db",
        "default_employee": "engineer",
        "keep_worktree": False,
        "test_command": "",
        "test_timeout_s": 600,
    },
    "dispatch": {
        "min_samples": 5,
        "score_margin": 0.10,
        "force_both_on_high_risk": True,
        "use_gemini": True,
        "engines": ["claude", "codex"],
    },
    "scoring": {
        "w_success": 0.5,
        "w_tests": 0.3,
        "w_revisions": 0.2,
        "revisions_cap": 3,
    },
    "policy": {"denylist": []},
}


# ---------------------------------------------------------------- root / env

def find_root(start: Path | None = None) -> Path:
    """crew.toml を上に辿って探す。環境変数 CREW_ROOT が優先。"""
    env = os.environ.get("CREW_ROOT")
    if env:
        return Path(env).resolve()
    cur = (start or Path.cwd()).resolve()
    for p in [cur, *cur.parents]:
        if (p / "crew.toml").exists():
            return p
    return cur


def load_dotenv(root: Path) -> None:
    """`.env` を読み、未設定の環境変数だけを埋める。"""
    path = root / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_settings(root: Path) -> dict:
    path = root / "crew.toml"
    data = {}
    if path.exists():
        with path.open("rb") as f:
            data = tomllib.load(f)
    return _merge(DEFAULT_SETTINGS, data)


def load_companies(root: Path) -> dict[str, dict]:
    """engine 名 → 会社設定。companies/*.toml を全部読む。"""
    out: dict[str, dict] = {}
    cdir = root / "companies"
    if not cdir.exists():
        return out
    for p in sorted(cdir.glob("*.toml")):
        with p.open("rb") as f:
            cfg = tomllib.load(f)
        eng = cfg.get("engine")
        if eng:
            cfg["_path"] = str(p)
            out[eng] = cfg
    return out


# ---------------------------------------------------------------- front-matter

def parse_front_matter(text: str) -> tuple[dict, str]:
    """`---` で囲まれた key: value 行を dict に。リストは `a, b` と `[a, b]` の両方に対応。"""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("\n")
    end = None
    for i in range(1, len(parts)):
        if parts[i].strip() == "---":
            end = i
            break
    if end is None:
        return {}, text
    meta: dict = {}
    for line in parts[1:end]:
        line = line.split("  #")[0].rstrip()  # 行末コメント
        if not line.strip() or ":" not in line:
            continue
        key, _, val = line.partition(":")
        key, val = key.strip(), val.strip()
        if val.startswith("[") and val.endswith("]"):
            val = [v.strip().strip('"').strip("'") for v in val[1:-1].split(",") if v.strip()]
        meta[key] = val
    body = "\n".join(parts[end + 1:]).lstrip("\n")
    return meta, body


def dump_front_matter(meta: dict, body: str) -> str:
    lines = ["---"]
    for k, v in meta.items():
        if isinstance(v, list):
            v = "[" + ", ".join(str(x) for x in v) + "]"
        lines.append(f"{k}: {'' if v is None else v}")
    lines.append("---")
    return "\n".join(lines) + "\n" + body


# ---------------------------------------------------------------- employees

@dataclass
class Employee:
    name: str
    description: str
    tools: list[str]
    body: str
    path: str


def list_employees(root: Path) -> list[Employee]:
    edir = root / "employees"
    out = []
    if not edir.exists():
        return out
    for p in sorted(edir.glob("*.md")):
        if p.name.upper() == "README.MD":
            continue
        meta, body = parse_front_matter(p.read_text(encoding="utf-8"))
        name = str(meta.get("name") or p.stem)
        tools = meta.get("tools", [])
        if isinstance(tools, str):
            tools = [t.strip() for t in tools.split(",") if t.strip()]
        out.append(Employee(name=name, description=str(meta.get("description", "")),
                            tools=list(tools), body=body, path=str(p)))
    return out


def load_employee(root: Path, name: str) -> Employee:
    for e in list_employees(root):
        if e.name == name:
            return e
    raise FileNotFoundError(f"社員 '{name}' が employees/ に見つかりません")


# ---------------------------------------------------------------- jobs

@dataclass
class Job:
    id: str
    title: str
    category: str
    risk: str
    complexity: str
    created_at: str
    spec: str = ""
    test_command: str | None = None
    path: str = ""
    status: str = "open"
    adopted_run_id: int | None = None
    extra: dict = field(default_factory=dict)


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def new_job_id(jobs_dir: Path, when: datetime | None = None) -> str:
    when = when or datetime.now()
    prefix = when.strftime("%Y%m%d")
    n = 0
    if jobs_dir.exists():
        for p in jobs_dir.glob(f"{prefix}-*.md"):
            m = re.match(rf"{prefix}-(\d+)\.md$", p.name)
            if m:
                n = max(n, int(m.group(1)))
    return f"{prefix}-{n + 1:03d}"


def write_job_file(jobs_dir: Path, job: Job) -> Path:
    jobs_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "id": job.id, "title": job.title, "category": job.category, "risk": job.risk,
        "complexity": job.complexity, "created_at": job.created_at,
        "test_command": job.test_command or "",
    }
    body = job.spec.strip() or "## 仕様\n（ここに、何をしてほしいかを書く）\n\n## 受け入れ条件\n（どうなっていれば合格か）\n"
    if not body.lstrip().startswith("#"):
        body = "## 仕様\n" + body + "\n"
    path = jobs_dir / f"{job.id}.md"
    path.write_text(dump_front_matter(meta, body), encoding="utf-8")
    job.path = str(path)
    return path


def read_job_file(jobs_dir: Path, job_id: str) -> Job:
    path = jobs_dir / f"{job_id}.md"
    if not path.exists():
        raise FileNotFoundError(f"案件票 {path} がありません")
    meta, body = parse_front_matter(path.read_text(encoding="utf-8"))
    tc = str(meta.get("test_command", "") or "").strip() or None
    return Job(
        id=str(meta.get("id", job_id)), title=str(meta.get("title", job_id)),
        category=str(meta.get("category", "other")), risk=str(meta.get("risk", "medium")),
        complexity=str(meta.get("complexity", "M")), created_at=str(meta.get("created_at", "")),
        spec=body, test_command=tc, path=str(path), extra=meta,
    )
