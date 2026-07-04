# progress — 進捗と注意点

作成日時: 2026-07-04 22:01
更新日時: 2026-07-04 22:55

## 現在の状態

**フェーズ1(基盤)完了。** SQLite スキーマ + Vault + rebuild + llama.cpp 2ポート疎通まで検証済み。次はフェーズ2(取り込み)。

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
- llama.cpp b9870(CUDA 13.3)を `runtime/llama.cpp/` にインストール(`--version` 検証済み)
- **フェーズ1(基盤)**:
  - `server/store.py`: スキーマ(articles / tombstones / category_briefs / FTS5 trigram / vec0 768次元)、URL 正規化 + dedup、状態遷移
  - `server/vault.py`: 記事 MD 読み書き(frontmatter + 本文往復一致)、`_tombstones.jsonl`、`_category-brief.md`、`rebuild_index()`
  - `server/llm.py`: llama-server クライアント(content / reasoning_content 分離)
  - `server/atomic_io.py`(lm-chat 移植)、`server/config.py` + `config/categories.yaml`
  - `tests/test_phase1.py`: dedup / tombstone / MD 往復 / rebuild / FTS 全パス
  - llama.cpp 2ポート疎通: 9B(8081)・35B(8082)とも起動・health・日本語応答を確認(VRAM 使用 ~31.7GB / 48GB)

## 未完了(次にやること)

- フェーズ2(取り込み): IngestWorker + ddgs 検索 + SSE(article.new)+ FastAPI 最小 API。ダッシュボードにタイトルが流れるところまで。
- 以降は [plan.md](plan.md) のフェーズ順。

## 注意点

- 仕様書では 35B は Q5 想定(~25GB)だが、ダウンロード済みは **Q4_K_M**。VRAM 予算とコンテキスト長の実測時に前提を合わせること。
- `data/news-vault/`、`config/categories.yaml`、`package.json` はまだ存在しない。フェーズ1〜2で作成する。
- 仕様書 §3 のサーバー起動フラグは vLLM 流のため llama-server では使えない(plan.md 判断メモ参照)。起動は `scripts/start-llama-server.ps1` を正とする。
- **thinking のオーバーヘッドが大きい**(一言回答に思考 ~1,000 トークン、max_tokens=512 だと本文が空)。9B の高頻度タスクは thinking 無効化か短思考プロンプトが必須(plan.md 判断メモ参照)。
- FTS5 trigram は3文字以上のクエリでしかヒットしない(2文字の日本語単語は検索不可)。UI の検索実装時に考慮する。
