# AI社員組織 CTO計画書 — 調査結果と最小構成（MVP）実装計画

作成日: 2026-09-19
状態: 計画提示（実装前）。本書の承認後に Phase 1 の実装へ進む。

---

## 0. 結論（先に3行）

1. **既存の「Claude Code株式会社」「Codex株式会社」は、このリポジトリにも、アクセスできる他のリポジトリにも存在しない。** 組織は本計画でゼロから作る。
2. 実行環境には Claude Code だけが入っている。Codex CLI と Gemini CLI は未導入だが、**npm から導入でき、3つとも「対話なし（ヘッドレス）実行」と「JSON出力」に対応している**ことを実機で確認済み。つまり「1つの司令塔から3つを呼び分ける」設計は技術的に成立する。
3. MVPは **Python標準ライブラリだけで動くCLI + SQLite（1ファイルの実績DB）** で組む。追加ライブラリなし、サーバーなし。API鍵が無くても動く「模擬エンジン」を同梱し、鍵が揃う前から動作確認できるようにする。

---

## 1. 現状調査の結果

### 1-1. リポジトリ `lajapan-dev/My_Crew`

| 項目 | 結果 |
|---|---|
| コミット数 | 1（`Add Kling AI MCP server config`） |
| ファイル | `.gitignore` / `.env.example` / `.mcp.json` の3つのみ |
| 内容 | 動画生成AI「Kling」を Claude Code から呼ぶための接続設定。AI社員組織とは無関係 |
| 他ブランチ | `claude/higgsfield-explanation-bl2jj4` があるが中身は同一 |
| 他リポジトリ | アクセス可能なリポジトリは本リポジトリのみ |

→ **「Claude Code株式会社」「Codex株式会社」に相当する社員定義・ワークフロー・実績データは一切ない。** もし本間さんの手元PCに別途あるなら、それを取り込む前提に切り替えられる（§6 参照）。

### 1-2. 実行環境

| ツール | 状態 | 補足 |
|---|---|---|
| Claude Code | **導入済み** v2.1.278 | `claude -p`（ヘッドレス）、`--output-format json`、`--json-schema`、`--permission-mode`、`--allowedTools/--disallowedTools` を確認 |
| Codex CLI | 未導入 → **導入可** v0.155.1 | `codex exec --json -o <file> --sandbox read-only\|workspace-write --output-schema <file> -C <dir> --ephemeral` を確認 |
| Gemini CLI | 未導入 → **導入可** v0.60.0 | `gemini -p --output-format json --approval-mode plan\|auto_edit\|yolo --sandbox` を確認 |
| Node.js | v22 | |
| Python | 3.11（`sqlite3` モジュール内蔵） | `sqlite3` コマンド自体は無いが Python から使えるので問題なし |
| API鍵 | **Anthropic以外は未設定** | `OPENAI_API_KEY` / `GEMINI_API_KEY` が無い。Codex・Gemini を実際に動かすには本間さんの鍵が必要（§6） |

用語メモ:
- **ヘッドレス実行** = 画面で対話せず、命令文を渡して結果だけ受け取る動かし方。プログラムから呼ぶために必須。
- **サンドボックス** = AIが触ってよい範囲（読むだけ／作業フォルダ内だけ書ける）を機械的に制限する仕組み。
- **ワークツリー** = 同じリポジトリの「作業用コピー」。本番のフォルダを汚さずにAIに作業させられる。

### 1-3. 本間さんのアカウントに同期されているスキル

`asa-brief`（朝ブリーフ）、`shift-hensei`、`business-plan-drafter` など。経営参謀ワークスペース用であり、AI社員組織とは別物。本計画では触らない（将来、社員の1人として組み込む余地はある）。

---

## 2. 設計の原則（本間さんの指示を仕様に翻訳）

| 指示 | 設計上の決定 |
|---|---|
| 2社を実行部隊として残す | 「会社」= **実行エンジンの設定ファイル**。Claude Code株式会社 = `engine: claude`、Codex株式会社 = `engine: codex` |
| 社員定義は共通化 | 社員 = **エンジン非依存の役割定義ファイル**（1役割1ファイル）。どちらの会社でも同じ社員を使う |
| 実行時だけ切り替え | 発注時に `--engine claude\|codex\|both` を決める。社員ファイルは書き換えない |
| 発注本部長は Gemini CLI | `dispatch-hq` という司令塔。**判断のみ**を担当し、コードには一切触らない（読み取り専用モードで起動） |
| 判断は数値で | 実績DBから **成功率・修正回数・テスト通過率** を集計し、スコア式で候補を出す。Gemini はその数値を見て最終判断し、**数値に逆らう場合は理由の明記を必須**にしてログに残す |
| 同じ仕事を二重に持たせない | 1案件 = 1発注記録。`both` は「比較モード」として明示的に区別し、結果は必ず片方だけ採用する |
| 共通の実績DB | SQLite 1ファイル `data/crew.db`。2社とも同じ表に書く |
| 本番に影響させない | 全実行を **ワークツリー内 + サンドボックス** で行い、成果物は「パッチ（差分）+ レポート」。適用・push・デプロイは人間だけが行う |
| まずCLI、後でダッシュボード | Phase 1 = CLI、Phase 2 = SQLiteから静的HTMLを1枚書き出す最小ダッシュボード |

---

## 3. 最小構成のフォルダ設計

```
My_Crew/
├── CLAUDE.md                     ← この組織の憲法（役割・禁止事項・読込順）
├── docs/
│   ├── PLAN.md                   ← 本書
│   └── ARCHITECTURE.md           ← 実装後に更新する図解（Phase 1 で作成）
│
├── employees/                    ← 【共通の社員定義】エンジン非依存
│   ├── README.md                 ← 社員ファイルの書き方
│   ├── engineer.md               ← 実装担当
│   ├── reviewer.md               ← レビュー担当
│   └── tester.md                 ← テスト担当
│
├── companies/                    ← 【実行部隊 = エンジン設定】
│   ├── claude-code-inc.toml      ← Claude Code株式会社（claude -p の起動条件）
│   ├── codex-inc.toml            ← Codex株式会社（codex exec の起動条件）
│   └── dispatch-hq.toml          ← 発注本部長（gemini -p、読み取り専用）
│
├── crew/                         ← 【CLI本体】Python 標準ライブラリのみ
│   ├── __main__.py               ← `python -m crew <command>`
│   ├── cli.py                    ← submit / dispatch / run / review / stats
│   ├── db.py                     ← SQLite スキーマと読み書き
│   ├── scoring.py                ← 成功率などの集計とスコア式（純粋関数・テスト対象）
│   ├── dispatcher.py             ← 発注本部長（ルール判定 + Gemini 判定）
│   ├── sandbox.py                ← ワークツリー作成・禁止コマンド検査
│   └── engines/
│       ├── base.py               ← 共通インターフェース（run(job, employee) → RunResult）
│       ├── claude_engine.py
│       ├── codex_engine.py
│       └── mock_engine.py        ← API鍵なしで流れを検証する模擬エンジン
│
├── jobs/                         ← 【案件票】1案件1ファイル（YYYYMMDD-NNN.md）
│   └── README.md
├── runs/                         ← 【成果物】パッチ・ログ・レポート（run_id ごと）※git管理外
├── data/
│   └── crew.db                   ← 【実績DB】※git管理外。スキーマは crew/db.py が正本
├── tests/                        ← scoring / dispatcher / db の単体テスト
├── .env.example                  ← OPENAI / GEMINI 鍵の欄を追加
└── .gitignore                    ← runs/ data/*.db .worktrees/ を追加
```

### 各引き出しの役割（なぜそこに置くか）

- **employees/**: 「誰が何を得意とし、何をしてはいけないか」だけを書く。どのAIで動かすかは書かない。だから2社で共有できる。形式は Claude Code のエージェント定義（Markdown + 先頭の設定行）に合わせる。Claude はそのまま読め、Codex/Gemini には本文を指示文として渡す。
- **companies/**: 「そのAIをどう起動するか」だけを書く。モデル名、サンドボックス種別、禁止ツール、タイムアウト。社員の中身はここに書かない。
- **jobs/**: 人間が書く発注票。雑に書いてよい。発注本部長がここから特徴（種類・リスク・複雑さ）を読み取る。
- **data/crew.db**: 2社の成績表。ここが「数値で判断する」ための唯一の根拠。
- **runs/**: AIの成果物置き場。本番に直接触らせず、ここに差分を出させて人間が採否を決める。

---

## 4. 実績DBとスコア式（「雰囲気ではなく数値」の中身）

### 4-1. 表の構成（SQLite）

| 表 | 主な列 | 役割 |
|---|---|---|
| `jobs` | id, title, category, risk, complexity, status, created_at | 案件票 |
| `dispatch_decisions` | job_id, decided_by(`rule`/`gemini`), decision(`claude`/`codex`/`both`), rule_scores_json, reason, overrode_rule(0/1) | 発注本部長の判断ログ |
| `runs` | job_id, engine, employee, outcome(`success`/`fail`/`partial`), tests_total, tests_passed, revisions, duration_s, tokens_in, tokens_out, patch_path | 実行結果 |
| `reviews` | run_id, verdict(`accept`/`reject`), reviewer(`human`), notes | 人間の採否（これが「成功」の定義） |

**成功の定義**: 人間が `accept` した run。テストが通っただけでは成功にしない。

### 4-2. 集計指標（エンジン × 案件カテゴリごと）

- **success_rate** = accept 数 ÷ run 数
- **test_pass_rate** = Σtests_passed ÷ Σtests_total
- **avg_revisions** = 平均修正回数（人間の差し戻し回数を含む）
- **n** = 件数（信頼度の判断に使う）

### 4-3. スコア式と判定ルール（初期値。運用しながら調整）

```
score(engine, category) = 0.5 × success_rate
                        + 0.3 × test_pass_rate
                        − 0.2 × min(avg_revisions / 3, 1)
```

1. 両エンジンとも同カテゴリで **n ≥ 5** なら、score の高い方に発注。
2. 差が **0.10 未満**、または片方でも n < 5 なら **`both`（比較モード）** にしてデータを貯める。
3. **risk = high** の案件は、n に関係なく `both` にして人間が見比べる。
4. Gemini（発注本部長）はこの計算結果を受け取り、最終決定を JSON で返す。ルールと違う決定をする場合は `reason` 必須、`overrode_rule=1` で記録。逆らった判断の正答率も後で集計できる。
5. Gemini が使えない（鍵なし・無料枠超過）ときは **ルール判定だけで進める**。司令塔の不在で組織が止まらないようにする。

**立ち上げ期の扱い（正直な前提）**: 最初はDBが空なので「数値で判断」はできない。よって最初の各カテゴリ5件程度は自動的に `both` になり、これが教師データになる。無料枠・コストを抑えたい場合は `--engine` で手動指定もできる。

---

## 5. 安全設計（初期段階の「本番に影響させない」）

| 層 | 仕組み |
|---|---|
| 作業場所 | run ごとに `git worktree` を切る。元のブランチは触らない |
| 実行権限 | Claude: `--permission-mode` + `--disallowedTools "Bash(git push*) Bash(rm -rf*) ..."`／Codex: `--sandbox workspace-write`（ネットワーク遮断）／Gemini: `--approval-mode plan`（読み取り専用） |
| 成果物 | AIは差分（パッチ）とレポートだけを出す。`crew review --accept` は人間のコマンド。`crew apply` はローカルブランチに当てるだけで push しない |
| 禁止コマンド | `sandbox.py` に禁止語リスト（push / deploy / docker push / 本番URL など）。エンジンのログに検出されたら run を `fail` にする |
| 鍵 | `.env` のみ（既に git 管理外）。ログに鍵を出さない |

---

## 6. 本間さんに確認したいこと（実装は止めずに進められるもの）

| # | 確認事項 | 仮置きの前提（回答が無ければこれで進める） |
|---|---|---|
| 1 | 「Claude Code株式会社」「Codex株式会社」の定義が手元PCなど別の場所に存在するか | 存在しない前提で新規作成。後から取り込み可能 |
| 2 | Codex の認証方法（`OPENAI_API_KEY` か ChatGPT ログインか） | 遠隔環境では対話ログインができないため **APIキー** 前提。`.env.example` に欄を追加 |
| 3 | Gemini の認証方法（`GEMINI_API_KEY` 無料枠） | 同上。APIキー前提 |
| 4 | 実装言語 | **Python 3.11 標準ライブラリのみ**（追加インストール不要・依存ゼロ）。Node 希望なら切替可 |
| 5 | 最初に置く社員は engineer / reviewer / tester の3名でよいか | 3名で開始。本間さんの業務（研修資料・Shopee分析）向け社員は Phase 3 で追加 |

---

## 7. 段階計画

### Phase 0 — 調査と計画（本書）✔ 完了

### Phase 1 — CLI最小MVP（次のセッションで実装）
成果物:
- `crew init`（DB作成・フォルダ作成）
- `crew submit "<案件タイトル>" --category bugfix --risk low --complexity S`（案件票を作りDBに登録）
- `crew dispatch <job_id>`（ルール判定 → Gemini 判定 → 決定ログ。`--dry-run` で判断だけ表示）
- `crew run <job_id> [--engine claude|codex|both] [--employee engineer]`（ワークツリーで実行、パッチとレポートを `runs/` へ）
- `crew review <run_id> --accept|--reject --note "..."`（人間の採否。ここが成功率の源）
- `crew stats [--category X]`（エンジン別成績表を表で表示）
- `mock_engine` により **鍵ゼロでも一連の流れが通る**。`tests/` で scoring と dispatcher を検証
- `CLAUDE.md` に組織の憲法（役割・禁止事項・読込順）を記述
- `.env.example` / `.gitignore` 更新

目安: 15ファイル前後、Python 700〜900行。1セッションで完了見込み。

**Phase 1 に含めないもの**（理由付き）:
- 比較モードの自動勝敗判定 → まず人間が見比べて、判断基準をDBに貯めてから自動化する
- 並列実行・キュー → 案件数が増えてから
- Slack/Chatwork 通知 → 通知先の設計が未定

### Phase 2 — 最小ダッシュボード
- `crew stats --html` で `runs/dashboard.html` を1枚生成（サーバー不要。既存の `http-server` で閲覧可）
- 表示: エンジン別 success_rate / test_pass_rate / avg_revisions、直近の発注判断一覧、Gemini がルールに逆らった判断とその結果
- 目安: 半セッション

### Phase 3 — 育てる段階（慣れてから）
- 比較モードの自動判定（テスト結果 + reviewer 社員の採点）
- 社員の追加（研修資料ドラフター、Shopee 売上分析など、本間さんの実業務向け）
- 経営参謀ワークスペース（`asa-brief`）との接続: 朝ブリーフから直接 `crew submit` する導線
- 発注本部長のモデル切替（Gemini 無料枠が足りなくなった場合の代替）

---

## 8. リスクと対処

| リスク | 対処 |
|---|---|
| Gemini 無料枠の上限 | 判断1回あたりの入力を数値表+案件票だけに絞る（数百トークン）。超過時はルール判定で継続 |
| Codex / Gemini の CLI 仕様変更 | エンジン層を1ファイルずつに分離。JSON出力の形が変わっても該当ファイルだけ直す |
| 実績が少ない段階での誤判断 | n < 5 は強制 `both`。人間の accept/reject が唯一の成功定義 |
| AIが本番に触る事故 | ワークツリー + サンドボックス + 禁止語検査 + push は人間のみ、の4重 |
| 二重発注 | `dispatch_decisions` に job_id の一意制約。`both` 以外で2 run は作れない |
