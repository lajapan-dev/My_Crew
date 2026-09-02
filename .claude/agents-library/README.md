# エージェントライブラリ(在庫 — そのままでは動かない)

公開されている定評あるサブエージェント集を4ソース・計841体同梱している。
**ここに置いてあるだけでは有効にならない**。`/setup` のヒアリングで必要なものを選ぶと、`.claude/agents/` にコピーされて有効化される(手動でコピーしてもよい)。

## 収録ソース(すべて MIT License、各フォルダに原文 LICENSE を同梱)

| フォルダ | 出典 | 体数 | 内容 |
|---|---|---|---|
| `wshobson-agents/` | [wshobson/agents](https://github.com/wshobson/agents) | 202 | 開発・インフラ・ビジネス系の定番エージェント(プラグイン別) |
| `voltagent-subagents/` | [VoltAgent/awesome-claude-code-subagents](https://github.com/VoltAgent/awesome-claude-code-subagents) | 158 | 10カテゴリ(開発・言語・インフラ・品質・データAI・ビジネス等) |
| `0xfurai-subagents/` | [0xfurai/claude-code-subagents](https://github.com/0xfurai/claude-code-subagents) | 138 | 言語・フレームワーク別エキスパート |
| `davepoon-collection/` | [davepoon/claude-code-subagents-collection](https://github.com/davepoon/claude-code-subagents-collection) | 343 | コミュニティ製プラグイン群(プラグイン別) |

## 有効化のルール

- 一度に有効化するのは **5体まで**。全体で有効なサブエージェントは10体以内を目安にする。
- 大量に有効化するとエージェント一覧がコンテキストを圧迫し、応答品質と振り分け精度が落ちる。
- 有効化したエージェントは `.claude/company/company-config.md` に記録する。
- 不要になったら `.claude/agents/` から該当ファイルを削除するだけで無効化できる(ライブラリ側は残る)。

## 注意

- 収録内容は各リポジトリの取得時点(2026-09-02)のスナップショット。
- 一部エージェントの frontmatter には `model:` 指定が含まれる。有効化時に古いモデル ID が指定されている場合は、その行を削除して既定モデルに任せることを推奨。
