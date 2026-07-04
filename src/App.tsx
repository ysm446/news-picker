import { useCallback, useEffect, useRef, useState } from "react";
import { api, openEvents } from "./api";
import type { Article, CategoryInfo, SseEvent } from "./types";
import { CategoryColumn } from "./components/CategoryColumn";
import { ChatPanel } from "./components/ChatPanel";
import { DetailPanel } from "./components/DetailPanel";
import { SettingsModal } from "./components/SettingsModal";
import { StatusBar } from "./components/StatusBar";

type ArticlesByCat = Record<string, Article[]>;

interface Filters {
  range: "all" | "1" | "3" | "7";
  impact: string;
  entity: string;
  savedOnly: boolean;
  hideNoise: boolean;
}

const NOISE_THRESHOLD = 30; // これ未満の relevance は「ノイズ」扱い

const NO_FILTERS: Filters = {
  range: "all",
  impact: "",
  entity: "",
  savedOnly: false,
  hideNoise: true,
};

function applyFilters(list: Article[], f: Filters): Article[] {
  const cutoff = f.range === "all" ? 0 : Date.now() / 1000 - Number(f.range) * 86400;
  const q = f.entity.trim().toLowerCase();
  return list.filter((a) => {
    if (
      f.hideNoise &&
      a.relevance !== null &&
      a.relevance < NOISE_THRESHOLD &&
      a.status !== "saved"
    ) {
      return false;
    }
    if (f.savedOnly && a.status !== "saved") return false;
    if (f.impact && a.impact !== f.impact) return false;
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
  const [briefs, setBriefs] = useState<Record<string, string>>({});
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Article | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [chat, setChat] = useState<{ articleId: number | null; title: string | null } | null>(null);
  const [filters, setFilters] = useState<Filters>(NO_FILTERS);
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
  const esRef = useRef<EventSource | null>(null);
  const selectedIdRef = useRef<number | null>(null);
  const loadedRef = useRef(false);
  const retryRef = useRef<number | null>(null);
  selectedIdRef.current = selected?.id ?? null;

  const loadAll = useCallback(async () => {
    try {
      const cats = await api.categories();
      setCategories(cats);
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
    if (ev.type === "article.new") {
      const card: Article = {
        id: ev.article.id,
        category: ev.category,
        title: ev.article.title,
        url: "",
        source: ev.article.source,
        snippet: null,
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
      };
      setArticles((prev) => {
        const list = prev[ev.category] ?? [];
        if (list.some((a) => a.id === card.id)) return prev;
        return { ...prev, [ev.category]: [card, ...list] };
      });
      playNotification();
    } else if (ev.type === "article.status_changed") {
      setArticles((prev) => {
        const next: ArticlesByCat = {};
        for (const [cat, list] of Object.entries(prev)) {
          next[cat] =
            ev.status === "hidden"
              ? list.filter((a) => a.id !== ev.id)
              : list.map((a) => (a.id === ev.id ? { ...a, status: ev.status } : a));
        }
        return next;
      });
    } else if (ev.type === "article.enriched") {
      setArticles((prev) => {
        const next: ArticlesByCat = {};
        for (const [cat, list] of Object.entries(prev)) {
          next[cat] = list.map((a) => (a.id === ev.article.id ? { ...a, ...ev.article } : a));
        }
        return next;
      });
      setSelected((prev) => (prev && prev.id === ev.article.id ? { ...prev, ...ev.article } : prev));
    } else if (ev.type === "article.enrich_failed") {
      if (selectedIdRef.current === ev.id) setDetailError(ev.detail);
    } else if (ev.type === "article.curated") {
      const byId = new Map(ev.scores.map((s) => [s.id, s.relevance]));
      setArticles((prev) => {
        const next: ArticlesByCat = {};
        for (const [cat, list] of Object.entries(prev)) {
          next[cat] = list.map((a) =>
            byId.has(a.id) ? { ...a, relevance: byId.get(a.id)! } : a,
          );
        }
        return next;
      });
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

  const onSave = useCallback((id: number) => {
    void api.save(id).catch(console.error); // 反映は SSE status_changed 経由
  }, []);

  const onHide = useCallback((id: number) => {
    void api.hide(id).catch(console.error);
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

  const onReloadConfig = useCallback(() => {
    api
      .reloadConfig()
      .then(() => loadAll())
      .catch(console.error);
  }, [loadAll]);

  const impactOptions = [...new Set(categories.flatMap((c) => c.impact_axis))];

  return (
    <div className={`app${showStatus ? " statusbar-on" : ""}`}>
      <header className="topbar">
        <h1 className="app-title">news-picker</h1>
        <div className="topbar-right">
          <button
            className="btn-icon"
            onClick={() => setChat({ articleId: null, title: null })}
          >
            チャット
          </button>
          <button className="btn-icon" onClick={() => setSettings({ editId: null })}>
            設定
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
          <span className={`conn ${connected ? "conn-ok" : "conn-ng"}`}>
            {connected ? "接続中" : "再接続中..."}
          </span>
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
        <select
          className="filter-select"
          value={filters.impact}
          onChange={(e) => setFilters({ ...filters, impact: e.target.value })}
        >
          <option value="">impact: 全て</option>
          {impactOptions.map((v) => (
            <option key={v} value={v}>{v}</option>
          ))}
        </select>
        <input
          className="filter-input"
          type="search"
          placeholder="ティッカー / 企業名 / タグで絞り込み (例: NVDA)"
          value={filters.entity}
          onChange={(e) => setFilters({ ...filters, entity: e.target.value })}
        />
        <label className="filter-check">
          <input
            type="checkbox"
            checked={filters.savedOnly}
            onChange={(e) => setFilters({ ...filters, savedOnly: e.target.checked })}
          />
          保存のみ
        </label>
        <label className="filter-check" title={`関連度 ${NOISE_THRESHOLD} 未満の記事を隠す (9B が自動採点)`}>
          <input
            type="checkbox"
            checked={filters.hideNoise}
            onChange={(e) => setFilters({ ...filters, hideNoise: e.target.checked })}
          />
          ノイズを隠す
        </label>
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
        {categories.map((c) => (
          <CategoryColumn
            key={c.id}
            category={c}
            articles={applyFilters(articles[c.id] ?? [], filters)}
            brief={briefs[c.id] ?? null}
            onSave={onSave}
            onHide={onHide}
            onOpen={onOpen}
            onSettings={(id) => setSettings({ editId: id })}
          />
        ))}
      </main>
      {chat === null && (
        <DetailPanel
          article={selected}
          loading={selected != null && selected.enriched_at == null}
          error={detailError}
          onClose={onCloseDetail}
          onDeepDive={onDeepDive}
        />
      )}
      {chat !== null && (
        <ChatPanel
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
      <StatusBar visible={showStatus} />
    </div>
  );
}

const API_HINT = "npm run server で起動";
