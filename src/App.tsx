import { useCallback, useEffect, useRef, useState } from "react";
import { api, openEvents } from "./api";
import type { Article, CategoryInfo, SseEvent } from "./types";
import { CategoryColumn } from "./components/CategoryColumn";
import { ChatPanel } from "./components/ChatPanel";
import { DetailPanel } from "./components/DetailPanel";

type ArticlesByCat = Record<string, Article[]>;

interface Filters {
  range: "all" | "1" | "3" | "7";
  impact: string;
  entity: string;
  savedOnly: boolean;
}

const NO_FILTERS: Filters = { range: "all", impact: "", entity: "", savedOnly: false };

function applyFilters(list: Article[], f: Filters): Article[] {
  if (f === NO_FILTERS) return list;
  const cutoff = f.range === "all" ? 0 : Date.now() / 1000 - Number(f.range) * 86400;
  const q = f.entity.trim().toLowerCase();
  return list.filter((a) => {
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
  const esRef = useRef<EventSource | null>(null);
  const selectedIdRef = useRef<number | null>(null);
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
      setError(null);
    } catch (e) {
      setError(`バックエンドに接続できません (${API_HINT})`);
      console.error(e);
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
      };
      setArticles((prev) => {
        const list = prev[ev.category] ?? [];
        if (list.some((a) => a.id === card.id)) return prev;
        return { ...prev, [ev.category]: [card, ...list] };
      });
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
    } else if (ev.type === "category.brief_updated") {
      setBriefs((prev) => ({ ...prev, [ev.category]: ev.brief }));
    }
  }, []);

  useEffect(() => {
    void loadAll();
    esRef.current = openEvents(handleEvent, setConnected);
    return () => esRef.current?.close();
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
    <div className="app">
      <header className="topbar">
        <h1 className="app-title">news-picker</h1>
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
        {categories.map((c) => (
          <CategoryColumn
            key={c.id}
            category={c}
            articles={applyFilters(articles[c.id] ?? [], filters)}
            brief={briefs[c.id] ?? null}
            onSave={onSave}
            onHide={onHide}
            onOpen={onOpen}
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
    </div>
  );
}

const API_HINT = "npm run server で起動";
