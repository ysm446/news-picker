# plan — 実装方針と優先順位

作成日時: 2026-07-04 22:01
更新日時: 2026-07-05 02:03

仕様の詳細は [../news-picker-spec.md](../news-picker-spec.md) を参照。ここでは実装の順序と判断を管理する。

## 実装フェーズ(仕様書 §14 に準拠)

1. **基盤**: SQLite スキーマ + Vault(MD 読み書き)+ rebuild。llama.cpp 2ポート疎通。
2. **取り込み**: IngestWorker + 検索MCP + dedup + SSE(article.new)。ダッシュボードにタイトルが流れるところまで。
3. **詳細生成**: EnrichWorker + 詳細パネル + MD 書き出し + 埋め込み/FTS 索引。
4. **保存/削除**: 状態遷移 + tombstone + CleanupWorker。
5. **カテゴリ要約**: BriefWorker(デバウンス)+ 列ヘッダ表示。
6. **深堀りチャット**: 35B + vault_search + Web検索MCP のエージェンティックループ。
7. **仕上げ**: フィルタ、トレイ常駐、config リロード。

各フェーズは「動くものが見える」単位で区切る。フェーズ2完了時点でダッシュボードとして最低限使い始められる。

## ディレクトリ構成(案)

仕様書 §12 の `news-desk/` 構成に従う(electron / src / server / config / news-vault)。

## 未解決課題(仕様書 §13)

- ~~検索MCP の選定~~ → 解決済み(判断メモ 2026-07-04 参照)。残タスクはレート制限とキャッシュ設計。
- 2モデル常駐時の KV キャッシュ VRAM 配分。コンテキスト長上限を実測して config 化。
- Ornith 9B の日本語ニュース要約品質の検証。不足なら要約だけ別モデル(Qwen 系)に差し替える余地を残す。
- 高頻度要約での `<think>` オーバーヘッド抑制(prompt / 停止条件)。
- published_at 欠損ソースの扱い(fetched_at で代替)。
- entity 抽出のティッカー表記ゆれ。

## 実装済み: 環境設定(アプリ設定) — 2026-07-05 完了

以下の設計で実装済み。項目候補 4(要約デバウンス)と 5(データルート選択)は未実装のまま残す。

## (元の計画) 環境設定(アプリ設定)

設定ウィンドウを拡張し、カテゴリ設定とは別に**環境設定**のセクションを設ける。

### 保存場所

- `data/settings.json`(git 管理外)。カテゴリ(data/categories.yaml)とはファイルを分ける。
- 書き込みは atomic_io 経由(lm-chat の settings_store.py パターンを移植)。
- API: `GET /settings` / `PUT /settings`(部分更新)。変更は即時反映(ワーカー再起動が必要な項目は明示)。
- 現状 localStorage にある表示系設定(通知音オン/オフ、リソースバー表示)は当面そのままでよいが、環境設定に統合するか実装時に判断する(統合するとバックエンド経由になる代わりに、UI 以外からも参照できる)。

### 設定項目の候補(優先順)

1. **ニュース見出しの日本語訳**(チェックボックス): 英語等の見出しを 9B で日本語化してカードに表示。
   - 実装案: キュレーション(curator.py のバッチ採点)と同じ 9B 呼び出しに相乗りさせ、「score + 必要なら translated_title」を1回で返す(呼び出し回数を増やさない)。DB は `articles.title_ja` カラム追加、UI は設定オンのとき title_ja 優先で表示。原文はツールチップ/詳細パネルで確認可能に。
2. **ノイズ閾値**: 現在 UI 定数(30)をスライダー等で調整可能に。
3. **記事の保持日数**: 現在 env 変数(NEWS_PICKER_RETENTION_DAYS=14)を設定画面から変更可能に。
4. **カテゴリ要約のデバウンス**(3件 / 15分)の調整。
5. **データルートの選択**(既存の判断メモ参照。環境設定画面に置くのが自然。変更は再起動要)。

### UI

- 設定モーダルをタブ構成にする: 「カテゴリ」(現行) / 「環境設定」(新規)。
- トップバーの「設定」ボタンからは従来どおりモーダルを開き、タブで切り替え。

## 判断メモ

- 2026-07-05: **検索クエリ設計の知見**(local-llm カテゴリのヒット激減を調査して判明)。ニュース検索 (ddgs news) はニュースメディアの索引なので、GGUF・llama.cpp・量子化のような**ニッチな専門用語はほぼ0件**になる(その話題はブログ圏にありニュース索引に無い)。**一般的な語・英語のクエリが圧倒的に強い**(実測: `local LLM` 15件 / `Hugging Face` 11件 / `新しい GGUF モデル` 0件)。英語見出しは日本語訳設定で吸収し、多義語のノイズ(Gemma→ファッション等)はキュレーションが除去する前提でクエリは広めに取るのが正解。

- 2026-07-04: **Web検索は自前実装にする**(mrkrsl/web-search-mcp は不採用)。理由: news モード・published_at がない、スクレイピングは24時間ポーリングに脆い、Node+Playwright が構成に加わる。取り込みループは Python `ddgs` ライブラリ直呼び(news 検索対応・API キー不要)、深堀りチャット側は Tavily API を併用(無料枠 月1,000クレジットのため高頻度ポーリングには使わない)。MCP プロトコル化は外部クライアントから使う必要が出てから薄いラッパーを被せる。
- 2026-07-04: **llama.cpp は GitHub Releases のビルド済みバイナリを `scripts/install-llama-server.ps1` で `runtime/llama.cpp/` に導入する**(cpu / cuda / vulkan 選択式、既定は auto 判定)。最新タグはCIビルド未完了でアセット0件のことがあるため「アセットのある最新リリース」を選ぶ。CUDA 既定は 13.3(Blackwell 対応)。将来的にアプリ(Electron)の初回セットアップからこの処理を呼べるようにする。
- 2026-07-04: **アプリ生成データは `data/` に集約**(SQLite 索引・ログ・キャッシュ、git 管理外)。MD 一次データは `data/news-vault/` とし、ここだけ git 管理する(仕様書 §12 のルート直下 `news-vault/` から変更)。
- 2026-07-05: **categories.yaml も個人データとして `data/categories.yaml` に移動**(ユーザー判断)。リポジトリには雛形 `config/categories.example.yaml` のみを置き、初回起動時に自動コピー(旧配置 `config/categories.yaml` があればそちらを優先して移行)。UI からのカテゴリ編集で git が汚れなくなる。
- 2026-07-05: **`data/` はアプリ repo で丸ごと git 管理外に変更**(ユーザー判断で上記を上書き)。ニュース MD は個人のローカルデータであり、公開リポジトリのコード履歴に混ぜない。仕様書の「vault は git 管理推奨」を実現したい場合は、data ルート側で独立リポジトリを作る(将来の data_root 選択案とセットで検討)。過去コミットには MD が残っている点に注意(完全に消したい場合は filter-repo で履歴書き換え + force push が必要)。
- 2026-07-04: 仕様書 §3 の `--reasoning-parser qwen3` / `--tool-call-parser qwen3_xml` は vLLM のフラグで、llama-server には存在しない。llama-server では `--jinja` でチャットテンプレート(tool-call パース・reasoning_content 分離)を有効にする(`scripts/start-llama-server.ps1` 参照)。
- 2026-07-04: **仕様書の「mem-chat」の実体は `D:\GitHub\lm-chat`**。調査の結果、フェーズ1・3の土台として十分流用可能。主なマッピング:
  - `store.py` ← `backend/store_base.py`(sqlite-vec ロード、FTS5 `tokenize='trigram'`(日本語部分一致)、vec0 `FLOAT[768]`)+ `store_memory.py` の `search_memory`(**RRF(k=60)+ 半減期式時間減衰のハイブリッド検索** — 「新着優先」にそのまま使える)
  - `embed.py` ← `backend/memory/embedder.py`(cl-nagoya/ruri-v3-310m + sentence-transformers、`normalize_embeddings=True`、lru_cache、warmup)
  - `sse.py` ← `routes/chat.py` + `routes/deps.py` の SSE フレーミング(`token`/`done`/`error` イベント、StreamingResponse)
  - `llm.py` ← `backend/llm_proxy.py`(urllib のみの llama-server クライアント、reasoning_content→`<think>` 変換のステートマシン)。tool-call は未実装なので深堀りチャット用に自前追加
  - `vault.py` ← `backend/atomic_io.py`(fsync + os.replace の原子的書き込み、破損時 .bak 退避)
  - 記事チャンク化 ← `backend/documents/chunker.py`(段落・日本語句読点境界 + オーバーラップ)
  - llama-server プロセス管理・**アプリ内ランタイムDLインストーラー** ← `backend/llama_manager.py`(GitHub Releases から CPU/CUDA/Vulkan を選択DL。Electron 統合時に `scripts/install-llama-server.ps1` の後継としてこの方式を採用できる)
  - 流用時の要改修点: (1) lm-chat は Ruri v3 の非対称プレフィックス(`検索クエリ: `/`検索文書: `)を付けていない → news-picker では `embed_query`/`embed_document` を分離して付与する。(2) workspace/session 等チャット固有スキーマの除去。(3) `web_search.py` はスタブなので検索は完全新規(ddgs + Tavily)。
  - 設計資料も参考になる: `D:\GitHub\lm-chat\docs\reference\rag\`(ハイブリッド検索の設計意図)、`runtime/context-length-and-vram.md`(VRAM/コンテキスト長の指針)
- 2026-07-04: 仕様書に登場する **rss-digest は参照しない**(ユーザー判断)。スケジューラ(APScheduler)とトレイ常駐は新規実装する。
- 2026-07-04: フェーズ1実装での仕様からの変更点:
  - FTS5 は仕様 §4.1 の外部コンテンツ表(`content='articles'`)ではなく**独立テーブル + 手動同期**にした(rebuild と削除処理が単純になる。lm-chat の実績パターン)。`tokenize='trigram'` で日本語の分かち書きなし部分一致に対応(**検索クエリは3文字以上必要**)。
  - **tombstone は vault 側(`_tombstones.jsonl`)にも永続化**する。DB だけに持つと rebuild で削除情報が消えて記事が復活するため。「MD が真実の源」の原則を削除情報にも適用した形。
  - **パージ時は記事 MD も削除する**(仕様 §6.4 は DB のみ言及)。MD を残すと rebuild で復活して tombstone と矛盾するため。
  - Python は `.venv`(Python 3.13)で管理。依存は `server/requirements.txt`。
- 2026-07-04: フェーズ2のスケジューラは **APScheduler ではなく asyncio タスク**(FastAPI lifespan 内でカテゴリごとに常駐ループ)で実装した。依存が減り、ポーリング + ジッタ程度なら十分。トレイ常駐(フェーズ7)の要件が出た時点で再検討する。
- 2026-07-04: ddgs の検索期間は **timelimit="w"(1週間)を既定**にした。"d"(24時間)はニッチな日本語クエリで0件になりやすく、DDG news バックエンドは短時間の連続利用で 403 を返すことも確認(Bing/Yahoo フォールバックは ddgs が自動で行う)。重複取り込みは dedup が吸収するので広めで問題ない。「全バックエンド0件」は正常系として INFO ログ扱い。
- 2026-07-04: **thinking オーバーヘッドを実測**(仕様 §13 の懸念が的中)。Ornith 9B/35B とも一言の回答に思考 ~1,000 トークンを消費し、max_tokens=512 では本文が空になる。フェーズ3の EnrichWorker では (a) `chat_template_kwargs: {enable_thinking: false}` での思考無効化(lm-chat の llm_proxy パターン)か (b) 短思考を強制する system prompt + 十分な max_tokens が必須。
