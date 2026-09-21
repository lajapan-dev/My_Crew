# 社員定義（employees/）

**ここは「誰が・何を得意とし・何をしてはいけないか」だけを書く場所です。**
どのAI（Claude / Codex）で動かすかは書きません。だから同じ社員を両社で使えます。

## ファイルの形

Claude Code のエージェント定義（`.claude/agents/*.md`）と同じ形です。
Claude はそのまま読め、Codex には本文を指示文として渡します。

```markdown
---
name: engineer
description: 一行で役割
tools: Read, Edit, Write, Bash, Grep, Glob   # Claude で許可する道具（Codex はサンドボックスで制御）
---
# 本文（役割・手順・禁止事項・成果物の出し方）
```

## 今いる社員

| name | 役割 |
|---|---|
| engineer | 実装担当。仕様を読み、最小の差分で実装しテストを通す |
| reviewer | レビュー担当。差分を読み、問題点を採点つきで報告する（コードは直さない） |
| tester | テスト担当。不足しているテストを追加し、実行結果を報告する |

## 追加するとき

1. このフォルダに `<name>.md` を作る（name は英小文字・ハイフン）
2. `python3 -m crew employees` で認識されているか確認する
3. `python3 -m crew run <job_id> --employee <name>` で使う

## 共通の安全規則

全社員のプロンプトには `crew/engines/base.py` の安全規則（本番禁止・push禁止・作業コピー内のみ）が自動で付きます。社員ファイルで緩めることはできません。
