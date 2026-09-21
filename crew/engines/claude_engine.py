"""Claude Code株式会社: `claude -p` をヘッドレスで呼ぶ。"""
from __future__ import annotations

from pathlib import Path

from ..config import Employee, Job
from .base import Engine, RunResult, build_prompt, iter_jsonl


class ClaudeEngine(Engine):
    name = "claude"

    def available(self) -> tuple[bool, str]:
        ok, why = super().available()
        if not ok:
            return ok, why
        return True, "ok（ログイン済みか ANTHROPIC_API_KEY が必要）"

    def argv(self, employee: Employee, system_text: str) -> list[str]:
        cfg = self.cfg
        argv = [self.command(), "-p", "--verbose", "--output-format", "stream-json",
                "--permission-mode", str(cfg.get("permission_mode", "acceptEdits")),
                "--append-system-prompt", system_text]
        if int(cfg.get("max_turns", 0) or 0) > 0:
            argv += ["--max-turns", str(int(cfg["max_turns"]))]
        if cfg.get("model"):
            argv += ["--model", str(cfg["model"])]
        if employee.tools:
            argv += ["--allowedTools", *employee.tools]
        if cfg.get("disallowed_tools"):
            argv += ["--disallowedTools", *[str(t) for t in cfg["disallowed_tools"]]]
        return argv

    def run(self, employee: Employee, job: Job, workdir: Path, run_dir: Path) -> RunResult:
        system_text, user_text = build_prompt(employee, job)
        argv = self.argv(employee, system_text)
        # 入れ子起動を拒否されないよう、親セッションの印を外す
        code, out, err, dur = self._exec(argv, workdir, user_text, int(self.cfg.get("timeout_s", 1200)),
                                         env_drop=("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"))
        res = RunResult(outcome="fail", exit_code=code, raw_log=out, stderr=err, duration_s=dur,
                        command_line=argv[:6] + ["..."])
        final = None
        for ev in iter_jsonl(out):
            t = ev.get("type")
            if t == "assistant":
                for block in (ev.get("message") or {}).get("content") or []:
                    if block.get("type") == "tool_use" and block.get("name") == "Bash":
                        cmd = (block.get("input") or {}).get("command")
                        if cmd:
                            res.commands.append(str(cmd))
            elif t == "result":
                final = ev
        if final is not None:
            res.output_text = str(final.get("result") or "")
            usage = final.get("usage") or {}
            # 入力トークンはキャッシュ生成・キャッシュ読取も含めて実態の量にする
            res.tokens_in = sum(int(usage.get(k) or 0) for k in
                                ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
            res.tokens_out = int(usage.get("output_tokens") or 0)
            res.cost_usd = final.get("total_cost_usd")
            is_err = bool(final.get("is_error")) or final.get("subtype") not in (None, "success")
            res.outcome = "fail" if is_err or (code not in (0, None)) else "success"
            if is_err:
                res.error = f"claude result subtype={final.get('subtype')}"
        else:
            res.error = f"claude から結果イベントが取れませんでした（exit={code}）: {err[-500:]}"
        return res
