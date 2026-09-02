# CLAUDE.md

メインエージェント本体の指示は最小限とし、実体は以下の2ファイルに分離している。

@.claude/base/common-rules.md
@.claude/company/company-config.md

- `base/common-rules.md`: 全導入先共通の実績あるルール。**編集しない**。
- `company/company-config.md`: 導入先企業ごとの意向。`/setup` で自動生成される。共通ルールと矛盾する場合はこちらを優先する。

初回起動時(company-config.md が未設定のとき)は、ユーザーに `/setup` の実行を一度だけ案内すること。
