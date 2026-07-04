# progress — 進捗と注意点

作成日時: 2026-07-04 22:01
更新日時: 2026-07-04 22:26

## 現在の状態

**フェーズ0(実装前)。** コードは未着手。仕様策定とモデル準備まで完了。

## 完了済み

- 仕様書の策定: [../news-picker-spec.md](../news-picker-spec.md)
- モデルのダウンロード: `models/Ornith-1.0-9B-GGUF/ornith-1.0-9b-Q4_K_M.gguf`、`models/Ornith-1.0-35B-GGUF/ornith-1.0-35b-Q4_K_M.gguf`
- プロジェクトルールの整備: AGENTS.md / CLAUDE.md、Electron デザインルール([../rules/electron-design-rules.md](../rules/electron-design-rules.md))
- 初回コミット準備: `.gitignore`(models / runtime / data を除外、`data/news-vault/` のみ git 管理)
- llama.cpp インストーラー: `scripts/install-llama-server.ps1`(cpu / cuda / vulkan 選択式、`runtime/llama.cpp/` に導入)。**まだ実行はしていない**
- llama-server 起動スクリプト: `scripts/start-llama-server.ps1`(9B: 8081 / 35B: 8082)
- Web検索方針の決定: 自前実装(ddgs + Tavily 併用)。詳細は [plan.md](plan.md) の判断メモ
- lm-chat(= 仕様書の mem-chat、`D:\GitHub\lm-chat`)の流用調査。マッピングは [plan.md](plan.md) の判断メモ
- 初回コミット(d3d5d53)

## 未完了(次にやること)

- `scripts/install-llama-server.ps1` の実行(環境は cuda 13.3 が適合: RTX PRO 5000 Blackwell / ドライバ 582.08)。
- フェーズ1(基盤): SQLite スキーマ + Vault + rebuild、llama.cpp 2ポート疎通。
- 以降は [plan.md](plan.md) のフェーズ順。

## 注意点

- 仕様書では 35B は Q5 想定(~25GB)だが、ダウンロード済みは **Q4_K_M**。VRAM 予算とコンテキスト長の実測時に前提を合わせること。
- `data/news-vault/`、`config/categories.yaml`、`package.json` はまだ存在しない。フェーズ1〜2で作成する。
- 仕様書 §3 のサーバー起動フラグは vLLM 流のため llama-server では使えない(plan.md 判断メモ参照)。起動は `scripts/start-llama-server.ps1` を正とする。
