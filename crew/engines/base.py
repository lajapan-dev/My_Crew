"""全エンジン共通のインターフェースと、社員プロンプトの組み立て。"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..config import Employee, Job

SAFETY_RULES = """【安全規則（必読・最優先）】
- あなたは隔離された作業コピー（git worktree）の中で作業しています。ここ以外のファイルには触れません。
- git push / git commit / デプロイ / 外部サービスへの書き込み / ネットワーク送信 / 破壊的コマンド（rm -rf 等）/ sudo は禁止です。
- 成果物は、この作業コピー内のファイル変更としてのみ残してください。commit は不要です（人間がレビュー後に行います）。
- テストを削除・スキップ・無効化して「通ったことにする」のは禁止です。
- 最後に「## 結果報告」の見出しで、変更ファイル・テスト結果・未解決事項を簡潔に書いてください。
"""


@dataclass
class RunResult:
    outcome: str                      # 'success' | 'fail'
    exit_code: int | None = None
    output_text: str = ""             # エンジンの最終メッセージ
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost_usd: float | None = None
    duration_s: float = 0.0
    raw_log: str = ""                 # 生ログ（JSONL 等）
    stderr: str = ""
    commands: list[str] = field(default_factory=list)   # 実行されたシェルコマンド（禁止語検査用）
    error: str | None = None
    command_line: list[str] = field(default_factory=list)


def build_prompt(employee: Employee, job: Job) -> tuple[str, str]:
    """(system_text, user_text) を返す。system は社員定義 + 安全規則、user は案件票。"""
    system_text = f"{SAFETY_RULES}\n【あなたの役割: {employee.name}】\n{employee.description}\n\n{employee.body.strip()}\n"
    user_text = (
        f"【案件票 {job.id}】{job.title}\n"
        f"種別: {job.category} / リスク: {job.risk} / 複雑さ: {job.complexity}\n\n"
        f"{job.spec.strip()}\n"
    )
    return system_text, user_text


class Engine:
    """サブクラスは available() と run() を実装する。"""
    name = "base"

    def __init__(self, company_cfg: dict, settings: dict):
        self.cfg = company_cfg
        self.settings = settings

    @property
    def display_name(self) -> str:
        return str(self.cfg.get("name") or self.name)

    def command(self) -> str:
        return str(self.cfg.get("command") or self.name)

    def available(self) -> tuple[bool, str]:
        """(使えるか, 理由)。鍵やログインの有無もここで見る。"""
        if shutil.which(self.command()) is None:
            return False, f"コマンド '{self.command()}' が見つかりません"
        return True, "ok"

    def run(self, employee: Employee, job: Job, workdir: Path, run_dir: Path) -> RunResult:  # pragma: no cover
        raise NotImplementedError

    # -------- helpers for subclasses
    def _exec(self, argv: list[str], cwd: Path, stdin_text: str | None, timeout_s: int,
              env_drop: tuple[str, ...] = ()) -> tuple[int | None, str, str, float]:
        env = dict(os.environ)
        for k in env_drop:
            env.pop(k, None)
        t0 = time.time()
        try:
            p = subprocess.run(argv, cwd=str(cwd), input=stdin_text, capture_output=True, text=True,
                               timeout=timeout_s, env=env)
            return p.returncode, p.stdout or "", p.stderr or "", time.time() - t0
        except FileNotFoundError as e:
            return None, "", f"コマンドが見つかりません: {e}", time.time() - t0
        except subprocess.TimeoutExpired as e:
            out = e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
            err = e.stderr.decode() if isinstance(e.stderr, bytes) else (e.stderr or "")
            return 124, out, err + f"\nTIMEOUT after {timeout_s}s", time.time() - t0


def iter_jsonl(text: str):
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue
