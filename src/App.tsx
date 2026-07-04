import { useCallback, useEffect, useRef, useState } from "react";
import { api, openEvents } from "./api";
import type { Article, CategoryInfo, SseEvent } from "./types";
import { CategoryColumn } from "./components/CategoryColumn";
import { ChatPanel } from "./components/ChatPanel";
import { DetailPanel } from "./components/DetailPanel";

type ArticlesByCat = Record<string, Article[]>;

export default function App() {
  const [categories, setCategories] = useState<CategoryInfo[]>([]);
  const [articles, setArticles] = useState<ArticlesByCat>({});
  const [briefs, setBriefs] = useState<Record<string, string>>({});
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Article | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [chat, setChat] = useState<{ articleId: number | null; title: string | null } | null>(null);
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
          <span className={`conn ${connected ? "conn-ok" : "conn-ng"}`}>
            {connected ? "接続中" : "再接続中..."}
          </span>
        </div>
      </header>
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
            articles={articles[c.id] ?? []}
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
