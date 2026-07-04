# news-picker

ダッシュボード型ニュースアプリ。ローカルLLM + Web検索で興味分野をカテゴリごとに自動監視し、Markdown に蓄積して RAG と深堀りチャットの材料にする。**すべてローカルで動作**し、ニュースデータが外部サービスに送られることはない(検索リクエストを除く)。

## 主な機能

- **カテゴリ別ダッシュボード** — kanban 風の列に新着ニュースがリアルタイム(SSE)で流れ込む。カテゴリは UI から追加・編集・削除可能
- **二層カデンス** — タイトル取り込みは数分毎・LLMなしで軽く、要約などの LLM 加工はクリック時のみ
- **AI キュレーション** — 取り込んだ記事を常駐モデルが関連度 0-100 で自動採点し、ノイズ(無関係な記事・宣伝)を自動で非表示。カテゴリごとに「オープンモデル限定」のような採点基準も書ける
- **見出しの日本語訳** — 英語ニュースの見出しを自動で日本語化(設定でオン/オフ)
- **カテゴリ要約** — 「いま何が起きているか」のロールアップを新着のたびに自動更新
- **詳細生成** — カードクリックで要約・要点・エンティティ(ティッカー等)・影響度を生成し、Markdown として蓄積
- **深堀りチャット** — ローカル記事庫(ハイブリッド検索)と Web 検索をエージェンティックに使い、出典付きで回答。ストリーミング + Markdown 表示
- **モデルは役割ベース** — 常駐モデル(軽量・要約/採点用)と深堀りモデル(高性能・チャット用)を `models/` の GGUF から選択。深堀りモデルはステータスバーからワンクリックでロード/アンロード(VRAM 節約)
- **トレイ常駐** — ウィンドウを閉じても取り込みは裏で継続

## 必要環境

- Windows(PowerShell 5.1+)
- Python 3.13 / Node.js 20+
- NVIDIA GPU 推奨(CPU でも動作可。インストーラーが cpu / cuda / vulkan を選択)
- GGUF 形式の LLM(例: 常駐用 ~5GB + 深堀り用 ~20GB)

## セットアップ

```powershell
# 1. Python 環境
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -r server\requirements.txt

# 2. フロントエンド
npm install
npm run build

# 3. llama.cpp (runtime/ に導入。GPU/CPU は自動判定)
powershell -ExecutionPolicy Bypass -File scripts\install-llama-server.ps1

# 4. モデルを models/ に配置 (フォルダ構成は任意、*.gguf を自動検出)
#    使用モデルはアプリの設定画面 (歯車 → 環境設定) で選択

# 5. 起動
.\start.bat
```

初回起動時に `config/categories.example.yaml` から `data/categories.yaml` が生成される。カテゴリの調整はアプリ内の歯車アイコンから。

停止は `stop.bat` またはトレイメニューの「終了」。

## アーキテクチャ

```
Electron + React (renderer)
   │  REST / SSE (:8100)
FastAPI (server/)
   ├─ IngestWorker   … ddgs ニュース検索 → dedup → SSE 配信 (LLM なし)
   ├─ Curator        … 常駐モデルで関連度採点 + 見出し翻訳
   ├─ EnrichWorker   … クリック時に要約生成 → MD 書き出し → 索引
   ├─ BriefWorker    … カテゴリ要約 (デバウンス)
   ├─ CleanupWorker  … 日次パージ (tombstone で復活防止)
   └─ chat_agent     … 深堀りチャット (vault_search + web_search)
   │
   ├─ llama-server ×2 (runtime/llama.cpp、常駐 :8081 / 深堀り :8082)
   ├─ SQLite + sqlite-vec + FTS5 (data/news.db、再構築可能な派生索引)
   └─ news-vault (data/news-vault/*.md、一次データ)
```

設計原則: **Markdown が真実の源**。SQLite 索引は `POST /admin/rebuild-index` でいつでも MD 群から全再構築できる。削除はソフト削除 + tombstone で、再取得しても復活しない。

## ディレクトリ

| パス | 内容 | git |
|---|---|---|
| `server/` | FastAPI バックエンド | 管理 |
| `src/` / `electron/` | React renderer / Electron main | 管理 |
| `config/categories.example.yaml` | カテゴリ設定の雛形 | 管理 |
| `data/` | 個人データ (vault MD、SQLite、categories.yaml、settings.json) | 管理外 |
| `models/` | GGUF モデル | 管理外 |
| `runtime/` | llama.cpp バイナリ | 管理外 |

## ドキュメント

- [docs/news-picker-spec.md](docs/news-picker-spec.md) — 仕様書
- [docs/plan/](docs/plan/) — goals / plan / progress(判断メモ含む)
- [docs/design/search-query-design.md](docs/design/search-query-design.md) — 検索クエリ設計ガイド
- [docs/changelog.md](docs/changelog.md) — 変更履歴
