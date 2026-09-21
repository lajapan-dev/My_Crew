"""発注本部長用: `gemini -p` を読み取り専用で呼び、JSON を取り出す。"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path


def gemini_available(cfg: dict) -> tuple[bool, str]:
    cmd = str(cfg.get("command") or "gemini")
    if shutil.which(cmd) is None:
        return False, f"コマンド '{cmd}' が見つかりません（npm install -g @google/gemini-cli）"
    if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") \
            or (Path.home() / ".gemini" / "oauth_creds.json").exists():
        return True, "ok"
    return False, "GEMINI_API_KEY が無い（.env に設定。無料枠で可）"


def ask_gemini(cfg: dict, prompt: str, cwd: Path) -> tuple[str | None, str]:
    """(応答テキスト, 生出力)。失敗時は (None, エラー文)。"""
    cmd = str(cfg.get("command") or "gemini")
    argv = [cmd, "-p", prompt, "--output-format", "json", "--approval-mode", "plan"]
    if cfg.get("model"):
        argv += ["-m", str(cfg["model"])]
    try:
        p = subprocess.run(argv, cwd=str(cwd), capture_output=True, text=True,
                           timeout=int(cfg.get("timeout_s", 120)))
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return None, f"gemini 起動失敗: {e}"
    raw = (p.stdout or "").strip()
    if p.returncode != 0 and not raw:
        return None, f"gemini exit={p.returncode}: {(p.stderr or '')[-500:]}"
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            if data.get("error"):
                return None, f"gemini error: {data['error']}"
            return str(data.get("response") or ""), raw
    except json.JSONDecodeError:
        pass
    return raw, raw


def extract_json(text: str) -> dict | None:
    """文中の最初の {...} を JSON として読む（コードフェンス対応）。"""
    if not text:
        return None
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    cands = [m.group(1)] if m else []
    start = text.find("{")
    if start >= 0:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    cands.append(text[start:i + 1])
                    break
    for c in cands:
        try:
            v = json.loads(c)
            if isinstance(v, dict):
                return v
        except json.JSONDecodeError:
            continue
    return None
