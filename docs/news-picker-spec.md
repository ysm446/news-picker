# news-picker 仕様書

ダッシュボード型ニュースアプリ。ローカルLLM(Ornith-1.0)+ Web検索MCP で、興味分野をカテゴリごとにリアルタイム監視し、裏でMDに蓄積してRAGと深堀りチャットの材料にする。

---

## 1. 概要とゴール

- 複数カテゴリ(半導体株、GPU、メモリ、AI、ローカルLLM 等)のニュースを**数分おきに自動チェック**し、タイトルを即時にダッシュボードへ流す。
- 一覧はタイトルのみ。クリックで初めて詳細(LLM要約)を生成する **on-demand 加工**。
- カードは**保存(ピン留め)**と**非表示(削除)**ができる。削除は再取得で復活しない。
- カテゴリごとに裏でLLMが「今の状況」ロールアップを生成し、新着があるたびに更新する。
- 取得したニュースはMDファイルとして蓄積し、後続の検索・深堀りチャットのRAG対象にする。

### 設計の核

1. **MDが真実の源、SQLiteは再構築可能な派生索引。** SQLite索引が壊れてもMDから全再構築できる。
2. **安いタイトル取り込みと、高いLLM加工を分離する(二層カデンス)。** 全記事をLLMに通さない。
3. **削除はソフト削除 + tombstone。** ハード削除すると次のポーリングで同じ記事が復活する。

---

## 2. 技術スタック

| レイヤ | 採用 | 備考 |
|---|---|---|
| フロント | Electron + React + TypeScript | カテゴリ列(kanban風)UI |
| バックエンド | FastAPI (Python) | ワーカー・スケジューラ・API |
| LLM | Ornith-1.0 GGUF (llama.cpp) | 9B Dense / 35B MoE の2ポート |
| 埋め込み | Ruri v3-310m | mem-chat から流用 |
| ストレージ | SQLite + sqlite-vec + FTS5 | ハイブリッド検索。mem-chat から流用 |
| Web検索 | MCP (Tavily 主 / DuckDuckGo 従) | Research-Bot の知見を流用 |
| リアルタイム | SSE (FastAPI → renderer) | mem-chat の SSE 実装を流用 |
| スケジューラ | APScheduler + トレイ常駐 | rss-digest のトレイ常駐パターン |

**既存資産の再利用:** スケジューラ+取り込みは rss-digest、検索・保存・埋め込み・SSE は mem-chat がほぼそのまま土台になる。純粋な新規実装は「カテゴリを第一級概念にする config 層」と「ダッシュボードUI」のみ。

---

## 3. モデル serving

Ornith-1.0 は Qwen 3.5 ベースの reasoning + tool-calling モデル。既定で `<think>…</think>` から始まり、推論は `reasoning_content` に分離される。OpenAI互換エンドポイントでMCPと直結できる。

### 起動(2ポート)

```bash
# 裏の高頻度処理用: 9B Dense (~6GB Q4)。要約にコンテキストは要らないので短く。
llama-server -hf deepreinforce-ai/Ornith-1.0-9B-GGUF \
  --port 8081 -c 32768 \
  --reasoning-parser qwen3 \
  --tool-call-parser qwen3_xml \
  --host 127.0.0.1

# チャット用: 35B MoE (~25GB Q5, active ~3B/token で高速)。文脈広め。
llama-server -hf deepreinforce-ai/Ornith-1.0-35B-GGUF \
  --port 8082 -c 131072 \
  --reasoning-parser qwen3 \
  --tool-call-parser qwen3_xml \
  --host 127.0.0.1
```

- サンプリング: `temperature=0.6, top_p=0.95, top_k=20`。
- 応答パース: `content` を本文、`reasoning_content` は破棄(またはデバッグ保存)。
- 高頻度の要約タスクでは思考が長くならないよう system prompt で明示的に短い思考を促す。

### VRAM 予算(RTX PRO 5000 / 48GB)

- 重み合計 ~31GB(9B Q4 ~6 + 35B Q5 ~25)。残り ~17GB を両モデルの KV キャッシュで分け合う。
- **コンテキスト長は VRAM 制約下のチューニング対象。** 9B は 32K で十分、35B チャットは 64K〜128K。262K フルは KV が肥大するので常用しない。
- 単純化したい場合は **35B 一本**でも可(35B は 9B の上位互換; 速度・精度とも上)。その場合バックグラウンドとチャットが同一サーバのキューを共有する点に注意。

### モデル割り当て

| 処理 | モデル | ポート |
|---|---|---|
| 詳細生成(要約・抽出) | 9B | 8081 |
| カテゴリ要約(ロールアップ) | 9B | 8081 |
| 深堀りチャット(エージェンティック検索) | 35B | 8082 |

---

## 4. データモデル

### 4.1 SQLite スキーマ

```sql
-- 記事本体
CREATE TABLE articles (
  id           INTEGER PRIMARY KEY,
  category     TEXT NOT NULL,
  title        TEXT NOT NULL,
  url          TEXT NOT NULL UNIQUE,
  url_hash     TEXT NOT NULL,              -- dedup キー (正規化URLのハッシュ)
  source       TEXT,                       -- ドメイン
  snippet      TEXT,                       -- 検索結果のスニペット
  published_at INTEGER,                    -- 記事公開時刻 (epoch, 取得できれば)
  fetched_at   INTEGER NOT NULL,           -- 取り込み時刻 (epoch)
  status       TEXT NOT NULL DEFAULT 'new',-- new | seen | saved | hidden
  -- 以下、詳細生成後に埋まる (それまで NULL)
  summary      TEXT,                       -- 一行要約
  key_points   TEXT,                       -- JSON 配列
  entities     TEXT,                       -- JSON {tickers, companies, models}
  impact       TEXT,                       -- カテゴリの impact_axis の値
  tags         TEXT,                       -- JSON 配列
  body         TEXT,                       -- 取得した本文 (任意)
  md_path      TEXT,                       -- MDファイルへのパス
  enriched_at  INTEGER
);
CREATE INDEX idx_articles_cat_status ON articles(category, status, fetched_at DESC);
CREATE UNIQUE INDEX idx_articles_hash ON articles(url_hash);

-- tombstone: パージ済み/削除済みのハッシュ。dedup が参照して復活を防ぐ
CREATE TABLE tombstones (
  url_hash   TEXT PRIMARY KEY,
  reason     TEXT NOT NULL,   -- deleted | purged
  created_at INTEGER NOT NULL
);

-- カテゴリ要約(ロールアップ)
CREATE TABLE category_briefs (
  category      TEXT PRIMARY KEY,
  brief         TEXT NOT NULL,
  article_count INTEGER NOT NULL,  -- 要約に含めた記事数
  updated_at    INTEGER NOT NULL,
  md_path       TEXT
);

-- ベクトル索引 (sqlite-vec)。次元は Ruri v3-310m に合わせる
CREATE VIRTUAL TABLE vec_articles USING vec0(
  article_id INTEGER PRIMARY KEY,
  embedding  FLOAT[768]
);

-- 全文索引 (FTS5)
CREATE VIRTUAL TABLE fts_articles USING fts5(
  title, summary, body,
  content='articles', content_rowid='id'
);
```

### 4.2 dedup ロジック

取り込み時、`url_hash` が **articles にも tombstones にも存在しない**場合のみ新規挿入する。

```
url_hash = sha1(normalize_url(url))   -- utm等のクエリ除去・末尾スラッシュ正規化
if exists in articles.url_hash: skip
if exists in tombstones.url_hash: skip   -- ★ 削除/パージ済みは復活させない
else: insert (status='new')
```

タイトル正規化一致・埋め込み近傍(cos > 0.9)の二次dedupは詳細生成後に任意で実施。

### 4.3 MDファイル構造

MDが一次データ。フロントマター(YAML)+ 本文。カテゴリ/日付でフォルダを切る。

```
news-vault/
  semiconductor-stocks/
    2026-07-04/
      nvda-hbm-supply.md
    _category-brief.md        -- カテゴリ要約(RAG対象)
  gpu/
    2026-07-04/
      blackwell-yield.md
```

記事MD:

```markdown
---
id: 1234
category: semiconductor-stocks
title: "NVIDIA raises HBM orders amid supply crunch"
url: https://example.com/article
source: example.com
published_at: 2026-07-04T09:00:00Z
fetched_at: 2026-07-04T09:03:12Z
status: seen
entities:
  tickers: [NVDA, TSM]
  companies: [NVIDIA, TSMC]
  models: []
impact: bullish
tags: [HBM, supply-chain, earnings]
---

## 要約
(一行要約)

## 要点
- ...
- ...

出典: https://example.com/article
```

SQLite索引はこのMD群から `rebuild` コマンドで完全再構築できること(必須要件)。

---

## 5. カテゴリ設定 (config)

カテゴリはコード変更なしで追加できるよう config 駆動にする。`config/categories.yaml`:

```yaml
categories:
  - id: semiconductor-stocks       # フォルダ名・DB値。lowercase-hyphen
    label: 半導体株                 # UI表示名
    keywords: [半導体, HBM, ファウンドリ, 露光]
    query_templates:               # クエリ生成の起点。ローテーション
      - "HBM 需給 {month}"
      - "TSMC 稼働率"
      - "NVDA 決算"
      - "対中 半導体 規制"
    poll_interval_sec: 300         # 取り込み間隔
    jitter_sec: 60                 # ±ジッタ(同時叩き回避)
    impact_axis: [bullish, neutral, bearish]
    max_window: 40                 # カテゴリ要約に含める直近記事数
    summary_prompt: |              # ロールアップ用ペルソナ
      あなたは半導体業界アナリスト。以下の直近記事から、
      投資判断に関係する動きを3〜5行で要約せよ。

  - id: local-llm
    label: ローカルLLM
    keywords: [llama.cpp, GGUF, quantization, MoE]
    query_templates: ["新しい GGUF モデル", "llama.cpp release", "量子化 手法"]
    poll_interval_sec: 600
    jitter_sec: 90
    impact_axis: [notable, minor]
    max_window: 30
    summary_prompt: |
      ローカルLLM動向の要約。新モデル・量子化・推論最適化に注目。
```

---

## 6. 処理パイプライン(二層カデンス)

### 6.1 高速取り込みループ(数分毎・LLMなし)

`IngestWorker`(カテゴリごとにスケジュール、`poll_interval_sec` + ジッタ):

```
1. query_templates から今回のクエリを選ぶ(ローテーション。{month}等を展開)
2. Web検索MCP を呼ぶ → [{title, url, snippet, published_at, source}]
3. 各結果を dedup(§4.2)
4. 新規のみ articles に status='new' で挿入
5. SSE で article.new を配信(タイトルのみ)
```

ここにモデルを噛ませない → 軽い。タイトルが即座に流れる。

### 6.2 詳細生成(クリック時のみ・9B)

`EnrichWorker`(オンデマンドキュー。カードクリックで enqueue):

```
1. 本文取得(web_fetch 相当)
2. 9B に投げ、JSON で {summary, key_points, entities, impact, tags} を得る
3. articles を UPDATE、enriched_at 記録
4. MDファイルを書き出し、md_path を記録
5. 埋め込み(Ruri)→ vec_articles、FTS5 に反映
6. status を 'seen' に更新
7. SSE で article.enriched を配信
```

既に enriched 済みならキャッシュを返すだけ(再生成しない)。

### 6.3 カテゴリ要約(新着トリガ・デバウンス・9B)

`BriefWorker`(カテゴリごと。前回要約以降に新着があり、かつ N件たまった or T分経過でトリガ):

```
1. そのカテゴリの直近 max_window 件(タイトル+一行要約)を集める
2. summary_prompt + 記事一覧を 9B に投げてロールアップ生成
3. category_briefs を UPSERT、_category-brief.md を書き出し
4. SSE で category.brief_updated を配信
```

差分ではなく**直近ウィンドウ全体を毎回渡して作り直す**(文脈の一貫性のため)。

### 6.4 自動整理(日次・CleanupWorker)

```
- status IN ('new','seen') かつ fetched_at が X日以前の行:
    url_hash を tombstones('purged') に退避 → 行を削除 → vec/fts からも削除
- status='saved' と 'hidden' は対象外
```

Vault肥大を防ぎつつ、tombstoneで復活も防ぐ。

---

## 7. カード状態遷移

```
[取り込み] --dedup--> new --(表示/既読)--> seen
                       │                     │
       クリック ───────┴──────► 詳細生成(enrich)
                       │                     │
        保存 ──────────┴─────────────────────┴──► saved  (自動整理の対象外)
        削除 ──────────┴─────────────────────┴──► hidden (tombstone登録)
                                                       │
                                       再取得時に dedup が除外
```

- `new` / `seen`: 通常カード。未読バッジで区別。
- `saved`: 保存コレクション。パージ対象外。
- `hidden`: UIから消去。行は残す(undo可)。dedup は url_hash で常に弾く。
- パージ: 古い new/seen を tombstones('purged') に退避して削除。

---

## 8. 深堀りチャット(35B・エージェンティック)

Ornith の自己スキャフォルディング(モデル自身がツール呼び出し・多段検索を組む)を活かす。

- **2つのツールをモデルに渡す:**
  - `vault_search(query)` — ローカルVault へのハイブリッド検索(vec + FTS + 時間減衰。mem-chat のロジック)。
  - Web検索MCP — コーパスが古い/薄い話題でその場で新規検索。
- モデルが必要に応じて両者を多段で呼び、引用付きで回答。引用は必ず MD/ソースURL に戻せること。
- カードクリックからチャット起動時は、その記事MDを初期コンテキストに投入。
- ストリーミングは llama.cpp SSE(mem-chat 流用)。`reasoning_content` は折りたたみ表示、`content` を本文に。

---

## 9. SSE イベント定義

`GET /events`(全体ストリーム):

```jsonc
{ "type": "article.new",            "category": "gpu", "article": { "id": 1234, "title": "...", "source": "...", "fetched_at": 0 } }
{ "type": "article.enriched",       "article": { "id": 1234, "summary": "...", "impact": "bullish", "tags": ["..."] } }
{ "type": "article.status_changed", "id": 1234, "status": "saved" }   // saved | hidden
{ "type": "category.brief_updated", "category": "gpu", "brief": "...", "updated_at": 0 }
```

---

## 10. FastAPI エンドポイント

```
GET  /categories                      -> config 一覧 + 未読件数
GET  /articles?category=&status=      -> カード一覧(タイトル中心、ページング)
GET  /articles/{id}                   -> 記事詳細(未 enrich なら enrich をトリガ)
POST /articles/{id}/enrich            -> 詳細生成をキューに積む
POST /articles/{id}/save              -> status='saved'
POST /articles/{id}/hide              -> status='hidden' + tombstone('deleted')
GET  /categories/{id}/brief           -> ロールアップ取得
POST /chat                            -> SSE ストリーム(深堀りチャット)
GET  /events                          -> SSE(全体イベント)
POST /admin/rebuild-index             -> MD から SQLite索引を全再構築
```

---

## 11. UI レイアウト

- **カテゴリ列(kanban風)**: カテゴリごとに縦カラム。列上部に「今日のブリーフ」= `category_briefs`。
- **カード**: 見出し + ソース + 時刻 + 未読バッジ + (enrich後は)impactバッジ・tags。ホバーで保存/非表示アクション。
- **詳細パネル**: カードクリックで右にスライドイン。要約・要点・出典・「このニュースを深堀り」ボタン。
- **フィルタ**: 日付範囲、entity(例: ティッカー `NVDA` を含む記事のみ)、impact。
- **チャットビュー**: Vault横断の深堀り。引用元カードへジャンプ可能。
- リアルタイム: SSE で新着カードが上からフェードイン。

---

## 12. ディレクトリ構成(案)

```
news-desk/
  electron/            # main プロセス、トレイ、スケジューラ起動
  src/                 # React + TS(renderer)
  server/
    workers/
      ingest.py        # IngestWorker
      enrich.py        # EnrichWorker
      brief.py         # BriefWorker
      cleanup.py       # CleanupWorker
    llm.py             # llama.cpp クライアント(2ポート)
    search_mcp.py      # Web検索MCPクライアント
    store.py           # SQLite / sqlite-vec / FTS5
    embed.py           # Ruri v3-310m
    vault.py           # MD 読み書き / rebuild
    sse.py             # イベントバス
    api.py             # FastAPI ルート
  config/
    categories.yaml
  news-vault/          # MD 一次データ(git 管理推奨)
```

---

## 13. 未解決課題・検討事項

- **検索MCPの選定と news モード**: Tavily の news 機能を主に。レート制限とキャッシュ設計。
- **KVキャッシュのVRAM配分**: 2モデル常駐時のコンテキスト長上限を実測して config 化。
- **9B の要約品質**: Ornith はコーディング特化の reasoning モデル。日本語ニュース要約の品質を要検証。不足なら要約だけ別モデル(Qwen系)に差し替える余地を残す。
- **thinking のオーバーヘッド**: 高頻度要約で `<think>` が伸びないよう prompt/停止条件を調整。
- **published_at 欠損**: 検索結果に公開時刻が無いソースの扱い(fetched_at で代替)。
- **entity 抽出の一貫性**: ティッカー表記ゆれ。将来的に企業関係グラフ(EDINET/yfinance)と突き合わせる拡張余地。

---

## 14. 実装フェーズ

1. **基盤**: SQLiteスキーマ + Vault(MD読み書き)+ rebuild。llama.cpp 2ポート疎通。
2. **取り込み**: IngestWorker + 検索MCP + dedup + SSE(article.new)。ダッシュボードにタイトルが流れるところまで。
3. **詳細生成**: EnrichWorker + 詳細パネル + MD書き出し + 埋め込み/FTS索引。
4. **保存/削除**: 状態遷移 + tombstone + CleanupWorker。
5. **カテゴリ要約**: BriefWorker(デバウンス)+ 列ヘッダ表示。
6. **深堀りチャット**: 35B + vault_search + Web検索MCP のエージェンティックループ。
7. **仕上げ**: フィルタ、トレイ常駐、config リロード。
