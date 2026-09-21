"""実行エンジンの登録簿。会社設定（companies/*.toml）の engine 名で引く。"""
from __future__ import annotations

from pathlib import Path

from .base import Engine, RunResult, build_prompt, SAFETY_RULES  # noqa: F401
from .claude_engine import ClaudeEngine
from .codex_engine import CodexEngine
from .mock_engine import MockEngine

_REGISTRY: dict[str, type[Engine]] = {
    "claude": ClaudeEngine,
    "codex": CodexEngine,
    "mock": MockEngine,
}


def engine_names() -> list[str]:
    return list(_REGISTRY)


def get_engine(name: str, companies: dict[str, dict], settings: dict) -> Engine:
    if name not in _REGISTRY:
        raise KeyError(f"未知のエンジン '{name}'。使えるのは: {', '.join(_REGISTRY)}")
    cfg = companies.get(name, {"engine": name, "name": name})
    return _REGISTRY[name](cfg, settings)
