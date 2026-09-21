# AI社員組織（My_Crew）— 運用憲法

このリポジトリは、**Claude Code株式会社** と **Codex株式会社** という2つの実行部隊と、
**発注本部長（Gemini CLI）** からなる AI社員組織の本体です。
CTO（Claude Code の対話セッション）は、この憲法に従って組織を設計・保守します。

## 目的
- 案件を「Claude に出す / Codex に出す / 両方に出して比べる」のいずれかに、**数値（成功率・修正回数・テスト通過率）で**振り分ける。
- 社員定義と実績DBを共通化し、実行エンジンだけを切り替える。
- **初期段階では、人間の承認なしに本番へ影響する操作を一切させない。**

## 読込順（この順で読めば全体が分かる）
1. `CLAUDE.md`（本書）
2. `docs/PLAN.md`（調査結果と設計判断の根拠）
3. `crew.toml`（全体設定の正本）→ `companies/*.toml`（会社＝エンジン設定）→ `employees/*.md`（社員）
4. 必要なときだけ `crew/` のコード、`jobs/`・`runs/` の個別ファイル

## 引き出しの役割
| 場所 | 中身 | 正本か |
|---|---|---|
| `employees/` | 社員定義。エンジン非依存 | 正本 |
| `companies/` | 会社＝エンジン起動設定（claude / codex / gemini） | 正本 |
| `crew.toml` | 全体設定（スコア式の重み、禁止語、閾値） | 正本 |
| `crew/` | CLI 本体（Python 標準ライブラリのみ） | 正本 |
| `jobs/` | 案件票（人間が書く。状態はDBが正本） | 仕様のみ正本 |
| `data/crew.db` | 実績DB。2社共通。git管理外 | 正本（ローカル） |
| `runs/` | 成果物：パッチ・ログ・レポート。git管理外 | 記録 |
| `.worktrees/` | 実行中の作業コピー。実行後に消える | 一時 |

## 役割分担
- **発注本部長（gemini）**: 判断のみ。読み取り専用モードで起動し、コードに触れない。
- **実行部隊（claude / codex）**: 作業コピーの中で実装し、パッチとレポートを出す。
- **人間**: `crew review` で採否を決め、`crew apply` でローカルに当て、自分で commit / push する。
- **CTO（このセッション）**: 組織の設計・保守。社員や会社を増減させるときは本書と `docs/PLAN.md` を更新する。

## 絶対ルール（社員・会社設定で緩めてはならない）
1. 実行部隊は必ず作業コピー（git worktree）+ サンドボックス内で動く。作業コピーは最新コミットから切るので、`run` の前に commit する。
2. push / デプロイ / 外部サービス書き込み / 破壊的コマンドは禁止（`crew.toml [policy].denylist`）。検出した run は `fail`。
3. `crew apply` はローカルに当てるだけ。commit と push は人間が行う。
4. 1案件に発注記録は1つ（DBの一意制約）。`both` は比較モードで、採用は必ず片方だけ。
5. 「成功」の定義は**人間が accept した run**。テストが通っただけでは成功にしない。
6. 発注本部長はルール判定の数値を必ず受け取り、逆らう場合は理由必須。固定ルール（高リスク→両社、実績不足→両社、利用可能エンジンが1つ→その1つ）は覆せない。
7. 鍵は `.env` のみ。ログ・レポート・コミットに鍵を書かない。

## 発注判定のスコア式（`crew/scoring.py` が正本）
```
score = 0.5 × 成功率 + 0.3 × テスト通過率 − 0.2 × min(平均修正回数 / 3, 1)
```
- 両エンジンとも同カテゴリで n ≥ 5 → 高い方。差 < 0.10 → both。
- どちらかが n < 5 → both（データを貯める）。risk = high → both。
- テスト実績が無いエンジンは、テスト通過率の代わりに成功率を使う。

## 日常のコマンド
```
python3 -m crew doctor                       # CLI と鍵の状態
python3 -m crew submit "件名" --category bugfix --risk low --complexity S --spec "..."
python3 -m crew dispatch <job_id>            # 発注先を決める（--dry-run で判断だけ）
python3 -m crew run <job_id>                 # 決定どおり実行（--engine で手動指定）
python3 -m crew review <run_id> --accept     # 人間の採否
python3 -m crew apply <run_id>               # 採用したパッチをローカルに当てる
python3 -m crew stats                        # エンジン別成績表
python3 -m crew stats --html                 # runs/dashboard.html を生成
```

## 迷ったら
- 新しい役割が欲しい → `employees/` に1ファイル追加。会社設定は触らない。
- 別のAIを使いたい → `companies/` に1ファイル追加し、`crew/engines/` にエンジンを1ファイル追加。
- 重みや閾値を変えたい → `crew.toml` だけ。コードは触らない。
- 本番に触りたい → 今期はやらない。人間が `apply` 後に自分で行う。
