import { useCallback, useEffect, useRef, useState } from "react";
import { api, openEvents } from "./api";
import type { AppSettings, Article, CategoryInfo, SseEvent } from "./types";
import { CategoryColumn } from "./components/CategoryColumn";
import { ChatPanel } from "./components/ChatPanel";
import { GearIcon } from "./components/icons";
import { DetailPanel } from "./components/DetailPanel";
import { SettingsModal } from "./components/SettingsModal";
import { StatusBar } from "./components/StatusBar";

type ArticlesByCat = Record<string, Article[]>;

interface Filters {
  range: "all" | "1" | "3" | "7";
  entity: string;
  savedOnly: boolean;
  hideNoise: boolean;
}

const NO_FILTERS: Filters = {
  range: "all",
  entity: "",
  savedOnly: false,
  hideNoise: true,
};

function applyFilters(list: Article[], f: Filters, noiseThreshold: number): Article[] {
  const cutoff = f.range === "all" ? 0 : Date.now() / 1000 - Number(f.range) * 86400;
  const q = f.entity.trim().toLowerCase();
  return list.filter((a) => {
    if (
      f.hideNoise &&
      a.relevance !== null &&
      a.relevance < noiseThreshold &&
      a.status !== "saved"
    ) {
      return false;
    }
    if (f.savedOnly && a.status !== "saved") return false;
    if (a.fetched_at < cutoff) return false;
    if (q) {
      const hit =
        a.title.toLowerCase().includes(q) ||
        a.entities?.tickers.some((t) => t.toLowerCase().includes(q)) ||
        a.entities?.companies.some((c) => c.toLowerCase().includes(q)) ||
        a.tags?.some((t) => t.toLowerCase().includes(q));
      if (!hit) return false;
    }
    return true;
  });
}

export default function App() {
  const [categories, setCategories] = useState<CategoryInfo[]>([]);
  const [articles, setArticles] = useState<ArticlesByCat>({});
  // 「保存のみ」フィルタ ON の間だけ使う保存済み全件のリスト (OFF 時は null)
  const [savedByCat, setSavedByCat] = useState<ArticlesByCat | null>(null);
  const [briefs, setBriefs] = useState<Record<string, string>>({});
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Article | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [chat, setChat] = useState<{ articleId: number | null; title: string | null } | null>(null);
  const [filters, setFilters] = useState<Filters>(NO_FILTERS);
  const [prefs, setPrefs] = useState<AppSettings | null>(null);
  const [showStatus, setShowStatus] = useState(
    () => localStorage.getItem("news-picker.statusbar") !== "off",
  );
  const [soundOn, setSoundOn] = useState(
    () => localStorage.getItem("news-picker.sound") !== "off",
  );
  const soundOnRef = useRef(soundOn);
  soundOnRef.current = soundOn;
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const lastPlayedRef = useRef(0);

  const toggleStatus = useCallback(() => {
    setShowStatus((prev) => {
      localStorage.setItem("news-picker.statusbar", prev ? "off" : "on");
      return !prev;
    });
  }, []);

  const toggleSound = useCallback(() => {
    setSoundOn((prev) => {
      localStorage.setItem("news-picker.sound", prev ? "off" : "on");
      return !prev;
    });
  }, []);

  const playNotification = useCallback(() => {
    if (!soundOnRef.current) return;
    const now = Date.now();
    if (now - lastPlayedRef.current < 10_000) return; // 連続新着では10秒に1回まで
    lastPlayedRef.current = now;
    if (audioRef.current === null) {
      audioRef.current = new Audio(`${import.meta.env.BASE_URL}news_update.mp3`);
      audioRef.current.volume = 0.5;
    }
    audioRef.current.play().catch(console.error);
  }, []);
  const [settings, setSettings] = useState<{ editId: string | null } | null>(null);
  const [filterMenuOpen, setFilterMenuOpen] = useState(false);
  const [catMenuOpen, setCatMenuOpen] = useState(false);
  const esRef = useRef<EventSource | null>(null);
  const selectedIdRef = useRef<number | null>(null);
  const loadedRef = useRef(false);
  const retryRef = useRef<number | null>(null);
  selectedIdRef.current = selected?.id ?? null;

  const loadAll = useCallback(async () => {
    try {
      const cats = await api.categories();
      setCategories(cats);
      api.getSettings().then(setPrefs).catch(console.error);
      const byCat: ArticlesByCat = {};
      await Promise.all(
        cats.map(async (c) => {
          byCat[c.id] = await api.articles(c.id);
        }),
      );
      setArticles(byCat);
      const briefEntries = await Promise.all(
        cats.map(async (c) => {
          try {
            const b = await api.brief(c.id);
            return [c.id, b.brief] as const;
          } catch {
            return null; // ブリーフ未生成 (404)
          }
        }),
      );
      setBriefs(Object.fromEntries(briefEntries.filter((e) => e !== null)));
      loadedRef.current = true;
      setError(null);
    } catch (e) {
      // 起動直後はバックエンドの自動起動が終わっていないことがあるため再試行する
      console.error(e);
      if (!loadedRef.current) {
        if (retryRef.current !== null) window.clearTimeout(retryRef.current);
        retryRef.current = window.setTimeout(() => void loadAll(), 2000);
      } else {
        setError(`バックエンドに接続できません (${API_HINT})`);
      }
    }
  }, []);

  const handleEvent = useCallback((ev: SseEvent) => {
    // articles と savedByCat (保存のみ表示用) の両方へ同じ更新を適用する
    const updateLists = (update: (list: Article[]) => Article[]) => {
      const apply = (prev: ArticlesByCat): ArticlesByCat => {
        const next: ArticlesByCat = {};
        for (const [cat, list] of Object.entries(prev)) next[cat] = update(list);
        return next;
      };
      setArticles(apply);
      setSavedByCat((prev) => (prev === null ? prev : apply(prev)));
    };
    if (ev.type === "article.new") {
      const card: Article = {
        id: ev.article.id,
        category: ev.category,
        title: ev.article.title,
        url: "",
        source: ev.article.source,
        snippet: null,
        image_url: ev.article.image_url ?? null,
        status: "new",
        fetched_at: ev.article.fetched_at,
        published_at: null,
        summary: null,
        key_points: null,
        entities: null,
        impact: null,
        tags: null,
        enriched_at: null,
        relevance: null,
        title_ja: null,
        rating: null,
      };
      setArticles((prev) => {
        const list = prev[ev.category] ?? [];
        if (list.some((a) => a.id === card.id)) return prev;
        return { ...prev, [ev.category]: [card, ...list] };
      });
      playNotification();
    } else if (ev.type === "article.status_changed") {
      updateLists((list) =>
        ev.status === "hidden"
          ? list.filter((a) => a.id !== ev.id)
          : list.map((a) => (a.id === ev.id ? { ...a, status: ev.status } : a)),
      );
      // 詳細パネルにも反映 (非表示になったら閉じる)
      setSelected((prev) => {
        if (!prev || prev.id !== ev.id) return prev;
        return ev.status === "hidden" ? null : { ...prev, status: ev.status };
      });
    } else if (ev.type === "article.enriched") {
      updateLists((list) =>
        list.map((a) => (a.id === ev.article.id ? { ...a, ...ev.article } : a)),
      );
      setSelected((prev) => (prev && prev.id === ev.article.id ? { ...prev, ...ev.article } : prev));
    } else if (ev.type === "article.enrich_failed") {
      if (selectedIdRef.current === ev.id) setDetailError(ev.detail);
    } else if (ev.type === "article.rated") {
      updateLists((list) =>
        list.map((a) => (a.id === ev.id ? { ...a, rating: ev.rating } : a)),
      );
      setSelected((prev) => (prev && prev.id === ev.id ? { ...prev, rating: ev.rating } : prev));
    } else if (ev.type === "article.curated") {
      const byId = new Map(ev.scores.map((s) => [s.id, s]));
      updateLists((list) =>
        list.map((a) => {
          const s = byId.get(a.id);
          return s
            ? {
                ...a,
                relevance: s.relevance ?? a.relevance,
                title_ja: s.title_ja ?? a.title_ja,
              }
            : a;
        }),
      );
    } else if (ev.type === "category.brief_updated") {
      setBriefs((prev) => ({ ...prev, [ev.category]: ev.brief }));
    }
  }, [playNotification]);

  useEffect(() => {
    void loadAll();
    esRef.current = openEvents(handleEvent, (ok) => {
      setConnected(ok);
      // SSE が (再) 接続できた = バックエンドが起きた合図なのでデータを取り直す
      if (ok) void loadAll();
    });
    return () => {
      esRef.current?.close();
      if (retryRef.current !== null) window.clearTimeout(retryRef.current);
    };
  }, [loadAll, handleEvent]);

  // 「保存のみ」フィルタ ON の間は保存済みを全件取得する
  // (通常一覧は新しい順 60 件のため、古い保存カードは窓から外れて届かない)
  useEffect(() => {
    if (!filters.savedOnly || categories.length === 0) {
      setSavedByCat(null);
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const byCat: ArticlesByCat = {};
        await Promise.all(
          categories.map(async (c) => {
            byCat[c.id] = await api.savedArticles(c.id);
          }),
        );
        if (!cancelled) setSavedByCat(byCat);
      } catch (e) {
        console.error(e);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [filters.savedOnly, categories]);

  const onSave = useCallback((id: number) => {
    void api.save(id).catch(console.error); // 反映は SSE status_changed 経由
  }, []);

  const onHide = useCallback((id: number) => {
    void api.hide(id).catch(console.error);
  }, []);

  const onLike = useCallback((id: number) => {
    void api.like(id).catch(console.error); // 反映は SSE article.rated 経由
  }, []);

  const onDismiss = useCallback((id: number) => {
    void api.dismiss(id).catch(console.error); // 反映は SSE status_changed 経由
  }, []);

  const onOpen = useCallback((article: Article) => {
    setDetailError(null);
    setSelected(article); // まずリストの情報で即表示
    // 全文取得 (未 enrich なら生成がキューされ、完了は SSE で届く)
    api
      .article(article.id)
      .then((full) => setSelected((prev) => (prev && prev.id === full.id ? full : prev)))
      .catch((e) => setDetailError(String(e)));
  }, []);

  const onCloseDetail = useCallback(() => {
    setSelected(null);
    setDetailError(null);
  }, []);

  const onDeepDive = useCallback((article: Article) => {
    setChat({ articleId: article.id, title: article.title });
  }, []);

  const onReorderCategories = useCallback(
    (draggedId: string, targetId: string) => {
      if (draggedId === targetId) return;
      const ids = categories.map((c) => c.id);
      const from = ids.indexOf(draggedId);
      const to = ids.indexOf(targetId);
      if (from < 0 || to < 0) return;
      const next = [...categories];
      const [moved] = next.splice(from, 1);
      next.splice(to, 0, moved);
      setCategories(next); // 楽観更新
      api.reorderCategories(next.map((c) => c.id)).catch((e) => {
        console.error(e);
        void loadAll(); // 保存に失敗したらサーバーの順序に戻す
      });
    },
    [categories, loadAll],
  );

  const onToggleCategory = useCallback(
    (id: string, enabled: boolean) => {
      // 楽観更新 (非表示は取り込みも止まるが、それはバックエンド側で反映される)
      setCategories((prev) => prev.map((c) => (c.id === id ? { ...c, enabled } : c)));
      api.setCategoryEnabled(id, enabled).catch((e) => {
        console.error(e);
        void loadAll();
      });
    },
    [loadAll],
  );

  const onReloadConfig = useCallback(() => {
    api
      .reloadConfig()
      .then(() => loadAll())
      .catch(console.error);
  }, [loadAll]);

  return (
    <div className={`app${showStatus ? " statusbar-on" : ""}`}>
      <header className="topbar">
        <div className="topbar-right">
          <button
            className="btn-icon"
            onClick={() => setChat({ articleId: null, title: null })}
          >
            チャット
          </button>
          <button className="btn-icon" onClick={onReloadConfig} title="categories.yaml を再読み込み">
            設定再読込
          </button>
          <button
            className="btn-icon"
            onClick={toggleSound}
            title="新着ニュースの通知音"
          >
            {soundOn ? "通知音: オン" : "通知音: オフ"}
          </button>
          <button
            className="btn-icon"
            onClick={toggleStatus}
            title="システムリソースの表示/非表示"
          >
            {showStatus ? "リソース非表示" : "リソース表示"}
          </button>
          <button
            className="btn-icon icon-btn"
            onClick={() => setSettings({ editId: null })}
            title="設定"
            aria-label="設定"
          >
            <GearIcon size={16} />
          </button>
        </div>
      </header>
      <div className="filter-bar">
        <select
          className="filter-select"
          value={filters.range}
          onChange={(e) => setFilters({ ...filters, range: e.target.value as Filters["range"] })}
        >
          <option value="all">全期間</option>
          <option value="1">24時間</option>
          <option value="3">3日</option>
          <option value="7">1週間</option>
        </select>
        <input
          className="filter-input"
          type="search"
          placeholder="ティッカー / 企業名 / タグで絞り込み (例: NVDA)"
          value={filters.entity}
          onChange={(e) => setFilters({ ...filters, entity: e.target.value })}
        />
        <div className="filter-menu-wrap">
          <button
            className={`filter-toggle${
              categories.some((c) => c.enabled === false) ? " filter-toggle-on" : ""
            }`}
            aria-expanded={catMenuOpen}
            title="カテゴリの表示/非表示 (非表示中は取り込みも止まる)"
            onClick={() => setCatMenuOpen((prev) => !prev)}
          >
            カテゴリ
          </button>
          {catMenuOpen && (
            <>
              <div className="filter-menu-backdrop" onClick={() => setCatMenuOpen(false)} />
              <div className="filter-menu">
                {categories.map((c) => (
                  <label key={c.id} className="filter-check">
                    <input
                      type="checkbox"
                      checked={c.enabled !== false}
                      onChange={(e) => onToggleCategory(c.id, e.target.checked)}
                    />
                    {c.label}
                  </label>
                ))}
              </div>
            </>
          )}
        </div>
        <div className="filter-menu-wrap">
          <button
            className={`filter-toggle${
              filters.savedOnly || !filters.hideNoise ? " filter-toggle-on" : ""
            }`}
            aria-expanded={filterMenuOpen}
            title="表示フィルタの切り替え"
            onClick={() => setFilterMenuOpen((prev) => !prev)}
          >
            フィルタ
          </button>
          {filterMenuOpen && (
            <>
              <div className="filter-menu-backdrop" onClick={() => setFilterMenuOpen(false)} />
              <div className="filter-menu">
                <label className="filter-check">
                  <input
                    type="checkbox"
                    checked={filters.savedOnly}
                    onChange={(e) => setFilters({ ...filters, savedOnly: e.target.checked })}
                  />
                  保存した記事のみ表示
                </label>
                <label
                  className="filter-check"
                  title="9B が自動採点した関連度が閾値未満の記事を隠す"
                >
                  <input
                    type="checkbox"
                    checked={filters.hideNoise}
                    onChange={(e) => setFilters({ ...filters, hideNoise: e.target.checked })}
                  />
                  ノイズを隠す (関連度 {prefs?.noise_threshold ?? 30} 未満)
                </label>
              </div>
            </>
          )}
        </div>
        {filters !== NO_FILTERS && (
          <button className="btn-icon" onClick={() => setFilters(NO_FILTERS)}>
            クリア
          </button>
        )}
      </div>
      {error && (
        <div className="error-banner">
          {error}
          <button className="btn-icon" onClick={() => void loadAll()}>再読み込み</button>
        </div>
      )}
      <main className="board">
        {categories.length === 0 && !error && (
          <p className="board-loading">バックエンドに接続しています...</p>
        )}
        {categories.filter((c) => c.enabled !== false).map((c) => (
          <CategoryColumn
            key={c.id}
            category={c}
            articles={applyFilters(
              // 保存のみ表示中は全件リスト (取得完了までは通常リストで代用)
              (filters.savedOnly ? savedByCat?.[c.id] : undefined) ?? articles[c.id] ?? [],
              filters,
              prefs?.noise_threshold ?? 30,
            )}
            brief={briefs[c.id] ?? null}
            translate={prefs?.translate_titles ?? false}
            showThumbnails={prefs?.show_thumbnails ?? true}
            onSave={onSave}
            onHide={onHide}
            onLike={onLike}
            onDismiss={onDismiss}
            onOpen={onOpen}
            onSettings={(id) => setSettings({ editId: id })}
            onReorder={onReorderCategories}
          />
        ))}
      </main>
      <DetailPanel
        article={selected}
        loading={selected != null && selected.enriched_at == null}
        error={detailError}
        translate={prefs?.translate_titles ?? false}
        showThumbnails={prefs?.show_thumbnails ?? true}
        besideChat={chat !== null}
        onClose={onCloseDetail}
        onDeepDive={onDeepDive}
        onSave={onSave}
        onLike={onLike}
        onDismiss={onDismiss}
        onRetry={() => selected && onOpen(selected)}
      />
      {chat !== null && (
        <ChatPanel
          key={chat.articleId ?? "vault"} // 深堀り対象の切替で会話履歴をリセットする
          articleId={chat.articleId}
          articleTitle={chat.title}
          onClose={() => setChat(null)}
        />
      )}
      {settings !== null && (
        <SettingsModal
          categories={categories}
          initialEditId={settings.editId}
          onClose={() => setSettings(null)}
          onChanged={() => void loadAll()}
        />
      )}
      <StatusBar visible={showStatus} connected={connected} />
    </div>
  );
}

const API_HINT = "npm run server で起動";
