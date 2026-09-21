# 処理の流れと部品の責務

## 1案件の流れ

```
人間  crew submit ──▶ jobs/<id>.md + DB(jobs)
                         │
       crew dispatch ──▶ dispatcher.py
                         │  ① db.engine_stats → scoring.rule_decide（数値のみ）
                         │  ② 固定ルールなら終了（gemini を呼ばない）
                         │  ③ それ以外は gemini_client.ask_gemini → validate_gemini
                         ▼
                      DB(dispatch_decisions)  ※1案件1件（UNIQUE）
                         │
       crew run ───────▶ runner.execute_run
                         │  ① sandbox.create_worktree（最新コミットから）
                         │  ② engines/<engine>.run（社員本文 + 安全規則 + 案件票）
                         │  ③ sandbox.run_tests → scoring.parse_test_output
                         │  ④ sandbox.capture_patch → runs/<run_id>/patch.diff
                         │  ⑤ sandbox.scan_violations（禁止語）→ 該当なら fail + system reject
                         │  ⑥ DB(runs) 更新、report.md 出力、作業コピー削除
                         ▼
人間  crew review ─────▶ DB(reviews)  ※accept が「成功」の唯一の定義。採用は案件につき1 run
人間  crew apply ──────▶ git apply（ローカルのみ。commit / push は人間）
       crew stats ─────▶ report.py（表 / dashboard.html）
```

## 部品と責務

| 部品 | 責務 | 触ってよい人 |
|---|---|---|
| `crew.toml` | 閾値・重み・禁止語・既定コマンド | 人間 |
| `companies/*.toml` | エンジンの起動条件（モデル、サンドボックス、禁止ツール） | 人間 |
| `employees/*.md` | 役割・手順・禁止事項（エンジン非依存） | 人間・CTO |
| `crew/config.py` | 設定・社員・案件票の読み書き | CTO |
| `crew/db.py` | SQLite スキーマと集計 SQL | CTO |
| `crew/scoring.py` | スコア式・ルール判定・テスト出力の解析（純粋関数） | CTO |
| `crew/dispatcher.py` | 発注本部長（ルール → Gemini → 検証） | CTO |
| `crew/runner.py` | 1回の実行パイプライン | CTO |
| `crew/sandbox.py` | 作業コピー・パッチ・禁止語・テスト実行 | CTO |
| `crew/engines/*` | 各 CLI の呼び出しと出力の読み取り | CTO |
| `crew/report.py` | 成績表・ダッシュボード | CTO |
| `crew/cli.py` | コマンドの入口（薄く保つ） | CTO |

## エンジン追加の手順

1. `crew/engines/<name>_engine.py` に `Engine` を継承したクラスを1つ書く（`available()` と `run()`）。
2. `crew/engines/__init__.py` の `_REGISTRY` に登録する。
3. `companies/<name>-inc.toml` を作る（`engine = "<name>"`）。
4. `crew.toml` の `[dispatch].engines` に加えると発注候補になる。

## 安全の4重

作業コピー → サンドボックス／禁止ツール → 禁止語検査 → 人間の review / apply。
どれか1つが破られても、本番（push・デプロイ）には届かない設計。
