"""Codex株式会社: `codex exec --json` をサンドボックス付きで呼ぶ。"""
from __future__ import annotations

import os
from pathlib import Path

from ..config import Employee, Job
from .base import Engine, RunResult, build_prompt, iter_jsonl

ALLOWED_SANDBOX = ("read-only", "workspace-write")


class CodexEngine(Engine):
    name = "codex"

    def available(self) -> tuple[bool, str]:
        ok, why = super().available()
        if not ok:
            return ok, why
        if os.environ.get("OPENAI_API_KEY") or (Path.home() / ".codex" / "auth.json").exists():
            return True, "ok"
        return False, "OPENAI_API_KEY も ~/.codex/auth.json も無い（codex login か .env）"

    def argv(self, workdir: Path, last_msg: Path) -> list[str]:
        cfg = self.cfg
        sandbox = str(cfg.get("sandbox", "workspace-write"))
        if sandbox not in ALLOWED_SANDBOX:
            raise ValueError(f"codex の sandbox は {ALLOWED_SANDBOX} のみ許可（指定: {sandbox}）")
        argv = [self.command(), "exec", "--json", "-o", str(last_msg), "--sandbox", sandbox,
                "-C", str(workdir), "--skip-git-repo-check", "--ephemeral"]
        if cfg.get("model"):
            argv += ["-m", str(cfg["model"])]
        for kv in cfg.get("extra_config", []) or []:
            argv += ["-c", str(kv)]
        argv.append("-")  # プロンプトは stdin
        return argv

    def run(self, employee: Employee, job: Job, workdir: Path, run_dir: Path) -> RunResult:
        system_text, user_text = build_prompt(employee, job)
        last_msg = run_dir / "codex_last_message.md"
        argv = self.argv(workdir, last_msg)
        prompt = f"{system_text}\n\n{user_text}"
        code, out, err, dur = self._exec(argv, workdir, prompt, int(self.cfg.get("timeout_s", 1200)))
        res = RunResult(outcome="fail", exit_code=code, raw_log=out, stderr=err, duration_s=dur,
                        command_line=argv[:8] + ["..."])
        tin = tout = 0
        seen_usage = False
        errors = []
        for ev in iter_jsonl(out):
            t = str(ev.get("type", ""))
            item = ev.get("item") or {}
            if item.get("type") == "command_execution" and item.get("command"):
                res.commands.append(str(item["command"]))
            usage = ev.get("usage") or item.get("usage")
            if isinstance(usage, dict) and ("input_tokens" in usage or "output_tokens" in usage):
                seen_usage = True
                tin += int(usage.get("input_tokens") or 0)
                tout += int(usage.get("output_tokens") or 0)
            if t == "error" or item.get("type") == "error":
                errors.append(str(ev.get("message") or item.get("message") or ev))
            if item.get("type") == "agent_message" and item.get("text"):
                res.output_text = str(item["text"])
        if last_msg.exists():
            res.output_text = last_msg.read_text(encoding="utf-8", errors="replace") or res.output_text
        if seen_usage:
            res.tokens_in, res.tokens_out = tin, tout
        if code == 0 and not errors:
            res.outcome = "success"
        else:
            res.error = "; ".join(errors)[:500] or f"codex exit={code}: {err[-500:]}"
        return res
