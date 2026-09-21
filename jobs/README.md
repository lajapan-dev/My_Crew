# 案件票（jobs/）

人間が書く「発注票」です。**雑に書いて構いません。** 発注本部長はここから種類・リスク・複雑さを読み取ります。

## 作り方

```
python3 -m crew submit "ログイン画面の文言修正" --category bugfix --risk low --complexity S --spec "「ログイン」を「サインイン」に統一"
```

→ `jobs/YYYYMMDD-NNN.md` ができます。仕様の追記はこのファイルを直接編集してください。

## ファイルの形

```markdown
---
id: 20260921-001
title: ログイン画面の文言修正
category: bugfix        # bugfix / feature / refactor / test / docs / research / other
risk: low               # low / medium / high（high は必ず両社比較になる）
complexity: S           # S / M / L
created_at: 2026-09-21T10:00:00
test_command:           # 省略可。書けば crew.toml の既定を上書き
---
## 仕様
（何をしてほしいか。曖昧でよい。判断が必要な点は「要判断」と書く）

## 受け入れ条件
（できれば。どうなっていれば合格か）
```

## 状態の流れ

`open` →（dispatch）→ `dispatched` →（run）→ `running` → `awaiting_review` →（review）→ `done`（採用）/ `rejected`（差し戻し。再 run 可）

状態はDBが正本です。`python3 -m crew list` で確認できます。
