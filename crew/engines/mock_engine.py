"""模擬エンジン: API鍵が無くても一連の流れ（作業コピー→変更→パッチ→DB）を検証する。"""
from __future__ import annotations

import os
from pathlib import Path

from ..config import Employee, Job
from .base import Engine, RunResult, build_prompt


class MockEngine(Engine):
    name = "mock"

    def available(self) -> tuple[bool, str]:
        return True, "ok（模擬）"

    def run(self, employee: Employee, job: Job, workdir: Path, run_dir: Path) -> RunResult:
        system_text, user_text = build_prompt(employee, job)
        mode = os.environ.get("CREW_MOCK_OUTCOME", "success")
        (workdir / "MOCK_RESULT.md").write_text(
            f"# mock output for {job.id}\n\n{job.title}\n\n(employee: {employee.name})\n", encoding="utf-8")
        cmds = ["ls", "python3 -m unittest discover -s tests -q"]
        if mode == "violation":
            cmds.append("git push origin main")
        report = "## 結果報告\n- 変更ファイル: MOCK_RESULT.md\n- テスト結果: 模擬\n- 未解決事項: なし\n"
        if mode == "fail":
            return RunResult(outcome="fail", exit_code=1, output_text="", error="mock failure",
                             tokens_in=10, tokens_out=5, duration_s=0.01, commands=cmds,
                             raw_log=system_text[:200])
        return RunResult(outcome="success", exit_code=0, output_text=report, tokens_in=1200, tokens_out=300,
                         cost_usd=0.0, duration_s=0.01, commands=cmds, raw_log=user_text[:200])
