# My Crew — Claude Code 導入パッケージ

顧客企業に Claude Code を導入するためのパッケージ。実績ある共通ルールをベースに、導入先ごとの意向を `/setup` の一問一答ヒアリングで反映する。

## 導入手順(導入担当者向け・約10分)

1. **このリポジトリを導入先の環境に配置する**(clone または zip 展開)
2. **API キーを設定する**
   ```bash
   cp .env.example .env
   # .env を開いて KLING_ACCESS_KEY / KLING_SECRET_KEY を記入
   # 取得先: https://app.klingai.com/global/dev/api-key
   ```
3. **Claude Code を起動する**(リポジトリのフォルダで `claude`)
4. **`/setup` を実行する** — Claude が一問一答で企業の意向(事業内容・ユースケース・口調・追加機能)をヒアリングし、確認後に企業別設定を自動生成する
5. 完了。以後は普通に使うだけ。設定をやり直したいときは `/setup` を再実行する

## パッケージ構成

```
CLAUDE.md                     メインエージェント(最小限 — 下記2ファイルを読み込むだけ)
.claude/
├── base/common-rules.md      全導入先共通の実績あるルール(編集しない)
├── company/company-config.md 導入先ごとの意向(/setup が自動生成)
├── agents/                   有効なサブエージェント
│   ├── kling-media-creator   動画・画像生成(Kling AI)
│   └── slide-creator         スライド・資料作成
├── agents-library/           エージェント在庫 841体(4つの公開集を同梱・/setupで有効化)
├── skills/setup/             /setup ヒアリングスキル
└── settings.json             チーム共通設定(MCP自動許可)
.mcp.json                     Kling AI MCP サーバー設定(mcp-kling@5.2.0 固定)
.env.example                  API キーのテンプレート(.env は git 管理外)
```

## 設計方針

- **パフォーマンス維持**: 実績ある共通ルール(`base/common-rules.md`)は全導入先で同一・無編集。常時有効のエージェントは少数に絞る。
- **意向の反映**: 企業ごとの違いは `company/company-config.md` に分離。共通ルールと矛盾する場合は企業設定を優先。
- **拡張**: 追加機能はライブラリ 841体から `/setup` で選んで有効化(一度に5体まで)。
