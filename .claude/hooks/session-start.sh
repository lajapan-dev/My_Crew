#!/bin/bash
# Claude Code on the web のセッション開始時に、AI社員組織の道具を自動で整える。
# - Codex CLI / Gemini CLI をリポジトリ同梱（package.json の固定バージョン）で導入
# - 実績DBと作業フォルダを作成
# ローカル（手元PC）では何もしない。手元では `npm install && python3 -m crew init` を一度実行する。
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-$(pwd)}"

echo "[crew] npm install（Codex CLI / Gemini CLI を同梱版で導入）"
npm install --no-audit --no-fund

if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  echo "export PATH=\"${CLAUDE_PROJECT_DIR:-$(pwd)}/node_modules/.bin:\$PATH\"" >> "$CLAUDE_ENV_FILE"
fi

echo "[crew] init（実績DB・フォルダ）"
python3 -m crew init >/dev/null

echo "[crew] doctor"
python3 -m crew doctor
