# progress — 進捗と注意点

作成日時: 2026-07-04 22:01
更新日時: 2026-07-05 01:10

## 現在の状態

**仕様書の実装フェーズ1〜7を全て完了(v0.1.0)。** 以降は運用しながらの改善フェーズ。変更履歴は [../changelog.md](../changelog.md) を参照。

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

- **フェーズ2(取り込み)バックエンド**:
  - `server/search_web.py`: ddgs ニュース検索(region=jp-jp、失敗時は空リストで次周期へ)
  - `server/sse.py`: イベントバス(購読者ごとのキュー、詰まったら取りこぼす)
  - `server/workers/ingest.py`: IngestWorker(クエリローテーション + {month} 展開 + ジッタ、最短30秒の下限)
  - `server/api.py`: spec §10 の API(categories / articles / save / hide / brief / events / rebuild-index)+ 開発用 `/admin/ingest-now`
  - `tests/test_phase2_smoke.py`: uvicorn 実起動での E2E(ライブ ddgs 取り込み2件 → SSE article.new → save/hide → rebuild)全パス

- **ダッシュボード UI(Electron + React + Vite)**:
  - カテゴリ列(kanban 風)、カード(タイトル / ソース / 相対時刻 / 未読バッジ / hover で保存・非表示)、列ヘッダにブリーフ表示枠、SSE 接続インジケータ
  - `electron/main.cjs`(dist があれば dist、なければ vite dev を読む)、`src/`(React 19 + TS)、ダークテーマ(docs/rules/electron-design-rules.md 準拠)
  - 実機確認: バックエンド起動 → 実記事7件取り込み → Electron ウィンドウで表示

- **フェーズ3(詳細生成)**:
  - `server/workers/enrich.py`: EnrichWorker(キュー式、重複 enqueue 防止、enrich 済みは再生成しない)。9B + thinking 無効 + 構造化出力(json_schema)で {summary, key_points, entities, impact, tags} を生成
  - `server/fetch_page.py`(trafilatura 本文抽出、失敗時 snippet 代替)、`server/embed.py`(Ruri v3-310m、**クエリ/文書プレフィックス分離**、CPU 実行)
  - `GET /articles/{id}` が未 enrich なら自動キュー、`POST /articles/{id}/enrich`、SSE `article.enriched` / `article.enrich_failed`
  - UI: 詳細パネル(右スライドイン、要約/要点/エンティティ/タグ/出典、生成中表示、「深堀り」ボタンはフェーズ6まで無効)
  - 実記事で E2E 確認: マイクロン HBM 記事 → 高品質な日本語要約(ticker MU 抽出、impact bearish)→ MD 4.4KB 書き出し → FTS + 768次元埋め込み索引

- **フェーズ4(自動整理)**: `server/workers/cleanup.py` — 日次で new/seen の古い記事を tombstones('purged') に退避して DB + 記事 MD を削除(saved/hidden は対象外)。保持日数は `NEWS_PICKER_RETENTION_DAYS`(既定14日)。`tests/test_phase4_cleanup.py` 全パス
- **フェーズ5(カテゴリ要約)**: `server/workers/brief.py` — 新着トリガ + デバウンス(3件たまる or 15分経過)、直近 max_window 件全体を 9B に渡して作り直し。`_category-brief.md` 書き出し + SSE `category.brief_updated`。実データで自動生成を確認(3カテゴリとも)
- 開発用エンドポイント: `/admin/brief-now` `/admin/cleanup-now` 追加

- **フェーズ6(深堀りチャット)**:
  - `server/search_vault.py`: vault_search(FTS 語単位 AND + ベクトル近傍 → RRF 融合 → 半減期30日の時間減衰)
  - `server/chat_agent.py`: 35B エージェンティックループ(vault_search / web_search の2ツール、最大6ステップ、出典 URL 必須のシステムプロンプト)
  - `POST /chat`: SSE でステージイベント配信(chat.thinking / tool_call / tool_result / answer / error / done)
  - UI: チャットパネル(記事の「深堀り」ボタン + トップバーの Vault 横断チャット、ツール実行の経過表示、思考の折りたたみ)
  - E2E 確認: 「HBM の需給は?」→ 35B が自律的に vault_search 実行 → 3記事から構造化回答 + 実 URL 3件を出典に引用
  - start.bat は 9B + 35B の両方を起動するように変更

- **フェーズ7(仕上げ)**:
  - フィルタバー: 期間(24h/3日/1週間)、impact、ティッカー・企業名・タグの部分一致、保存のみ(クライアントサイドフィルタ)
  - トレイ常駐: ウィンドウを閉じてもトレイに残り取り込み継続。トレイメニューから開く/終了
  - config リロード: `POST /admin/reload-config` + UI「設定再読込」ボタン(ワーカー再構築)
  - Electron 自動起動: main.cjs がバックエンド(:8100)と llama-server(8081/8082)の未起動分だけを spawn し、終了時に自分が起動した分だけ kill。E2E 確認済み(Electron 単体起動 → 3コンポーネント全て up)

- **ステータスバー**(v0.1.0 後の追加): `server/system_stats.py`(lm-chat の routes/util.py を移植、psutil + pynvml)+ `GET /system/resources` + `src/components/StatusBar.tsx`。CPU / RAM / GPU / VRAM / 9B・35B 稼働ランプ、2秒ポーリング、表示状態は localStorage に永続化。スクリーンショットで表示確認済み

- **カテゴリ管理 UI + 起動改善**(v0.1.0 後の追加): カテゴリ CRUD API(categories.yaml へ書き戻し + ワーカー再構築。ハンドラは async 必須 — 同期だとスレッドプール実行になり ensure_future が失敗する)、設定モーダル、起動時リトライ、ready-to-show、1920x1080

- **キュレーション**: `server/curator.py`(9B バッチ採点、思考無効 + 構造化出力)+ `articles.relevance` 列 + SSE `article.curated` + UI「ノイズを隠す」(閾値30)。実測: 芸能・スポーツ・カテゴリ違いが10〜25点、業界の重要ニュースが85〜90点に正しく分離

- **35B オンデマンド化**: `server/llama_manager.py`(lm-chat 簡略移植: ポート引数でプロセス特定 + psutil で安全停止)+ `/llama/35b/start|stop` + ステータスバーのトグル。既定は 9B のみ起動(start.bat / Electron 自動起動とも)。35B オフ時は chat_agent が 9B にフォールバック。実測: アンロードで VRAM 30.9→8.9GB、9B 代行チャットも出典付きで動作

- **環境設定**: `data/settings.json` + `GET/PUT /settings` + 設定モーダルのタブ化。見出しの日本語訳(9B、キュレーション採点に相乗り、`articles.title_ja` 列)、ノイズ閾値、保持日数。実測: AI全般カテゴリの英語見出し29/30件が自然な日本語訳に

- **キュレーション学習・第1弾**: 評価ボタン(👍 / 興味なし)+ few-shot 注入(保存/👍 = 正例、興味なし/非表示 = 負例を採点プロンプトに同梱)。評価済みはパージ除外。第2弾以降(埋め込みスコア・ドメイン統計)は plan.md の実装予定を参照

## 未完了(改善候補)

- 環境設定の追加項目: 要約デバウンスの調整、データルート選択(plan.md 参照)。
- モデル役割の追加候補: 役割ごとのコンテキスト長設定、埋め込みモデルの差し替え。

- チャットのトークン単位ストリーミング(現状は各ターン一括。ツール呼び出しパースの堅牢性を優先した)。
- 深堀りチャットの引用元カードへのジャンプ(spec §11)。
- Tavily API の組み込み(深堀りチャットの検索品質向上。現状 web_search は ddgs のみ)。
- 埋め込みの再構築バッチ(rebuild 後の vec_articles 埋め直し)。
- 二次 dedup(タイトル正規化一致・埋め込み近傍 cos > 0.9。spec §4.2 の任意項目)。

## 起動方法

- **通常起動: `start.bat`**(9B llama-server + バックエンド + Electron を一括起動。起動済みのものはスキップ)
- 停止: `stop.bat`(注意: electron.exe を全て kill するので他の Electron 開発アプリと併用時は個別停止)
- 開発時の個別起動:
  1. バックエンド: `npm run server`(= `.venv\Scripts\python -m uvicorn server.api:app --port 8100`)
  2. アプリ: `npm run build` 済みなら `npm run app`(`ELECTRON_RUN_AS_NODE` に注意 → CLAUDE.md)。UI 開発中は `npm run dev` + ブラウザでも可
  3. llama-server: `scripts\start-llama-server.ps1 -Model 9b|35b|both`

## 注意点

- 仕様書では 35B は Q5 想定(~25GB)だが、ダウンロード済みは **Q4_K_M**。VRAM 予算とコンテキスト長の実測時に前提を合わせること。
- `data/news-vault/`、`config/categories.yaml`、`package.json` はまだ存在しない。フェーズ1〜2で作成する。
- 仕様書 §3 のサーバー起動フラグは vLLM 流のため llama-server では使えない(plan.md 判断メモ参照)。起動は `scripts/start-llama-server.ps1` を正とする。
- **thinking のオーバーヘッドが大きい**(一言回答に思考 ~1,000 トークン、max_tokens=512 だと本文が空)。9B の高頻度タスクは thinking 無効化か短思考プロンプトが必須(plan.md 判断メモ参照)。
- FTS5 trigram は3文字以上のクエリでしかヒットしない(2文字の日本語単語は検索不可)。UI の検索実装時に考慮する。
- 9B の日本語ニュース要約品質(仕様 §13 の懸念)は実測で良好。thinking 無効化 + 構造化出力の組み合わせで安定した JSON が返る。
- `enriched_at` は索引反映(FTS/埋め込み)より先に立つ。SSE `article.enriched` は全処理完了後に飛ぶので UI は問題ないが、REST ポーリングで enriched_at だけ見ると索引未完了の瞬間がある。
