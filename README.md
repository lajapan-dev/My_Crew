# My_Crew — AI社員組織（Claude Code株式会社 / Codex株式会社 / 発注本部長）

案件を **Claude Code** か **Codex** か **両方比較** に振り分け、作業コピーの中で実行し、
パッチとレポートを出す。振り分けは **実績DB（成功率・テスト通過率・修正回数）** に基づき、
**発注本部長（Gemini CLI）** が最終判断する。人間の承認なしに本番へ影響する操作はしない。

設計の根拠は `docs/PLAN.md`、運用ルールは `CLAUDE.md`。

## 必要なもの
- Python 3.11 以上（追加ライブラリ不要）
- git
- 実行部隊: `claude`（Claude Code）、`codex`（`npm install -g @openai/codex`）
- 発注本部長: `gemini`（`npm install -g @google/gemini-cli`）、`GEMINI_API_KEY`（無料枠可）

どれが無くても `mock` エンジンで一連の流れは試せる。

## 5分で試す
```bash
cp .env.example .env            # 鍵を書く（無くても mock は動く）
python3 -m crew init            # DB とフォルダを作る
python3 -m crew doctor          # CLI と鍵の状態を確認
python3 -m crew submit "READMEに使い方を1行追記" --category docs --risk low --complexity S \
    --spec "README.md の末尾に『動作確認済み』と1行追記する"
python3 -m crew dispatch 20260921-001 --dry-run     # 発注判断だけ見る
python3 -m crew run 20260921-001 --engine mock      # 模擬エンジンで流れを確認
python3 -m crew review 1 --accept --note "OK"
python3 -m crew stats
```

**注意**: 実行部隊は「最新コミット」から作業コピーを切ります。未コミットの変更は見えないので、`run` の前に commit してください。

実エンジンで動かすときは `--engine` を外す（発注本部長の決定どおりに動く）か、
`--engine claude` / `--engine codex` / `--engine both` を指定する。

## コマンド一覧
| コマンド | 役割 |
|---|---|
| `init` | DB・フォルダ作成 |
| `doctor` | CLI・鍵・git の状態確認 |
| `submit` | 案件票を作る |
| `dispatch <job>` | 発注先を決める（ルール判定 → 発注本部長） |
| `run <job>` | 作業コピーで実行し、パッチとレポートを `runs/<run_id>/` へ |
| `review <run> --accept/--reject` | 人間の採否（これが成功率の源） |
| `apply <run>` | 採用パッチをローカルに当てる（commit / push は人間） |
| `stats [--html]` | エンジン別成績表 / ダッシュボード生成 |
| `list [jobs\|runs]` | 一覧 |
| `employees` | 社員一覧 |

## テスト
```bash
python3 -m unittest discover -s tests -v
```
