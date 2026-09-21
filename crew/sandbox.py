"""作業コピー（git worktree）・パッチ取得・禁止語検査・テスト実行。"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=check)


def is_git_repo(root: Path) -> bool:
    return _git(root, "rev-parse", "--is-inside-work-tree", check=False).returncode == 0


def has_commits(root: Path) -> bool:
    return _git(root, "rev-parse", "--verify", "HEAD", check=False).returncode == 0


def create_worktree(root: Path, worktree_dir: str, name: str, base_ref: str = "HEAD") -> Path:
    """root の base_ref から独立した作業コピーを切る。元ブランチは触らない。"""
    wt = root / worktree_dir / name
    wt.parent.mkdir(parents=True, exist_ok=True)
    if wt.exists():
        remove_worktree(root, wt)
    _git(root, "worktree", "add", "--detach", str(wt), base_ref)
    return wt


def remove_worktree(root: Path, wt: Path) -> None:
    _git(root, "worktree", "remove", "--force", str(wt), check=False)
    if wt.exists():
        shutil.rmtree(wt, ignore_errors=True)
    _git(root, "worktree", "prune", check=False)


def capture_patch(wt: Path) -> tuple[str, str]:
    """作業コピー内の全変更（新規ファイル含む）を (patch, stat) で返す。commit はしない。"""
    _git(wt, "add", "-A")
    patch = _git(wt, "diff", "--cached", "--binary").stdout
    stat = _git(wt, "diff", "--cached", "--stat").stdout
    _git(wt, "reset", "-q", check=False)
    return patch, stat


def scan_violations(commands: list[str], denylist: list[str]) -> list[str]:
    """実行されたコマンド列を禁止語（正規表現）で検査し、該当したコマンドを返す。"""
    pats = [re.compile(p, re.I) for p in denylist]
    hits = []
    for cmd in commands:
        for pat in pats:
            if pat.search(cmd or ""):
                hits.append(f"{pat.pattern} <= {cmd.strip()[:200]}")
                break
    return hits


def run_tests(wt: Path, command: str, timeout_s: int) -> tuple[int | None, str]:
    if not command.strip():
        return None, ""
    try:
        p = subprocess.run(command, shell=True, cwd=str(wt), capture_output=True, text=True, timeout=timeout_s)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired as e:
        return 124, f"TIMEOUT after {timeout_s}s\n{(e.stdout or '')}{(e.stderr or '')}"


def apply_patch(root: Path, patch_path: Path, check_only: bool = False) -> tuple[bool, str]:
    args = ["apply", "--check", str(patch_path)] if check_only else ["apply", str(patch_path)]
    p = _git(root, *args, check=False)
    return p.returncode == 0, (p.stdout or "") + (p.stderr or "")


def working_tree_dirty(root: Path) -> bool:
    """追跡中ファイルに未コミットの変更があるか。案件票などの未追跡ファイルは汚れとみなさない。"""
    return bool(_git(root, "status", "--porcelain", "--untracked-files=no", check=False).stdout.strip())
