# CLAUDE.md

このファイルは、Claude Code がこのリポジトリで作業する際のプロジェクトルールです(AGENTS.md を Claude Code 向けに再構成したもの)。

## プロジェクト概要

**news-picker**: ダッシュボード型ニュースアプリ。ローカルLLM(Ornith-1.0)+ Web検索MCP で、興味分野をカテゴリごとにリアルタイム監視し、裏で Markdown に蓄積して RAG と深堀りチャットの材料にする。

詳細仕様は [docs/news-picker-spec.md](docs/news-picker-spec.md) を参照。

### 設計の核(変更時に必ず守る)

1. **MD が真実の源、SQLite は再構築可能な派生索引。** `POST /admin/rebuild-index` で MD 群から SQLite を全再構築できることが必須要件。
2. **二層カデンス。** 安いタイトル取り込み(数分毎・LLMなし)と、高い LLM 加工(クリック時のみ)を分離する。全記事を LLM に通さない。
3. **削除はソフト削除 + tombstone。** ハード削除すると次のポーリングで同じ記事が復活する。dedup は articles と tombstones の両方を参照する。

### 技術スタック

- フロント: Electron + React + TypeScript(kanban 風カテゴリ列 UI)
- バックエンド: FastAPI (Python) — ワーカー・スケジューラ・API
- LLM: Ornith-1.0 GGUF (llama.cpp) — 9B Dense(port 8081、背景処理)/ 35B MoE(port 8082、深堀りチャット)の2ポート構成。モデルは `models/` 配下
- ストレージ: SQLite + sqlite-vec + FTS5、埋め込みは Ruri v3-310m
- Web検索: 自前実装(取り込みは Python `ddgs` 直呼び、深堀りチャットは Tavily API 併用)、リアルタイムは SSE
- 既存資産の再利用: 検索・保存・埋め込み・SSE は mem-chat を土台にする
  - **mem-chat の実体は `D:\GitHub\lm-chat`**(仕様書内の呼称と異なるので注意)。流用マッピングは [docs/plan/plan.md](docs/plan/plan.md) の判断メモを参照
  - 仕様書に登場する rss-digest は**参照しない**(スケジューラ・トレイ常駐は新規実装)

### ディレクトリ規約

- `models/` — GGUF モデル(git 管理外)
- `runtime/` — llama.cpp 等の実行バイナリ(git 管理外)。`scripts/install-llama-server.ps1` で導入する
- `data/` — アプリが生成するデータの置き場(SQLite 索引、ログ、キャッシュ等。git 管理外)
  - 例外: `data/news-vault/` は MD 一次データなので git 管理する
- `scripts/` — セットアップ・起動スクリプト(`install-llama-server.ps1` / `start-llama-server.ps1`)

## 基本方針

- このプロジェクト固有の説明、判断基準、運用ルールは日本語で書く。
- コード、コマンド、API 名、ファイルパス、識別子は既存の表記を優先し、無理に翻訳しない。
- 既存の実装方針を確認してから変更する。
- ユーザーの未コミット変更を勝手に戻さない。
- 変更は必要な範囲に留め、無関係な整形やリファクタリングを混ぜない。

## 作業開始時の確認

作業前に、まず以下を確認する。

1. [docs/plan/goals.md](docs/plan/goals.md) — プロジェクトの目的、完成形、重視する価値。
2. [docs/plan/plan.md](docs/plan/plan.md) — 実装方針、優先順位、今後の予定。
3. [docs/plan/progress.md](docs/plan/progress.md) — 現在の進捗、完了済み作業、未完了作業、注意点。

今回の依頼が現在の計画や進捗のどこに関係するかを把握してから作業する。方針と矛盾しそうな場合は、実装前に確認する。

## ドキュメント管理

- `docs/**/*.md` を新規作成または内容更新するときは、本文の先頭付近に作成日時と更新日時を書く。
- 日時は `YYYY-MM-DD HH:MM` 形式で記録する。
- 既存ドキュメントを更新した場合は、更新日時を現在の作業日時に更新する。
- 例:
  - `作成日時: 2026-05-19 22:10`
  - `更新日時: 2026-05-19 22:10`
- `docs/changelog.md` は Git 履歴やユーザー向け変更を追うための履歴として使う(日本語で書く)。
- `docs/reference/` 配下は設計資料、仕様メモ、調査資料を置く場所として使う。
- `docs/plan/` 配下(goals / plan / progress)は進捗管理用の入口として保つ。
- UI 実装時は [docs/rules/electron-design-rules.md](docs/rules/electron-design-rules.md) のデザインルールに従う。

## バージョン管理

- アプリのバージョンは `package.json` の `version` を基準にする。
- ユーザー向けの明確な変更を行った場合は、必要に応じて `docs/changelog.md` に記録する。
- 未確定の変更は、必要に応じて先頭付近に「未リリース」セクションを作って記録する。
- バージョン見出しや履歴見出しに日時を書く場合は `YYYY-MM-DD HH:MM` 形式を使う。

## ファイル操作・コマンド実行

- ファイルの読み書きは Claude Code 標準の Read / Edit / Write ツールを使う。
- テキストファイルは UTF-8(BOM なし)で保存する。PowerShell でファイルを書く必要がある場合は BOM が付かないよう注意する(`Out-File` のデフォルトは UTF-16 なので避ける)。
- `.ps1` スクリプトは ASCII のみで書く(Windows PowerShell 5.1 は BOM なし UTF-8 を ANSI と解釈し、日本語コメントが文字化け・構文エラーの原因になるため)。
- ファイル・コード検索は Glob / Grep ツールを優先する。シェルで検索する場合は `rg` / `rg --files` を使う。
- 各コマンドでは、使う値を先に定義してから使う。
- 例では具体的な実ファイル名ではなく、必要に応じて `path/to/file.ext` のような一般的なパスを使う。
- **Electron を起動するときは `ELECTRON_RUN_AS_NODE` 環境変数を必ず解除する**(この開発環境のシェルは VSCode から同変数を継承しており、付いたままだと Electron が素の Node.js として動き `app` が undefined になる)。

## Python 環境

- Python はリポジトリ直下の venv(`.venv/`、Python 3.13)を使う。グローバル環境にインストールしない。
- 実行は `.venv\Scripts\python`、依存追加は `server/requirements.txt` に記載してから `.venv\Scripts\python -m pip install -r server\requirements.txt`。
- venv がない場合の再作成: `py -3.13 -m venv .venv`

## 検証

- フロントエンドや型に関わる変更後は、可能な限り `npm run build` を実行する。
- バックエンド Python の変更後は `.venv\Scripts\python tests\test_phase1.py` 等の検証スクリプトを実行する。最低限 `py_compile` で構文確認する。
- 検証できなかった場合は、その理由を作業報告に書く。
