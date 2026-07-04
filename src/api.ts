import type {
  AppSettings,
  Article,
  Brief,
  CategoryConfig,
  CategoryInfo,
  ChatEvent,
  ModelInfo,
  SseEvent,
  SystemStats,
} from "./types";

export const API_BASE = "http://127.0.0.1:8100";

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, init);
  if (!res.ok) throw new Error(`${res.status} ${path}`);
  return (await res.json()) as T;
}

export const api = {
  categories: () => fetchJson<CategoryInfo[]>("/categories"),
  articles: (category: string, limit = 60) =>
    fetchJson<Article[]>(`/articles?category=${encodeURIComponent(category)}&limit=${limit}`),
  article: (id: number) => fetchJson<Article>(`/articles/${id}`), // 未 enrich なら生成がキューされる
  brief: (category: string) => fetchJson<Brief>(`/categories/${encodeURIComponent(category)}/brief`),
  save: (id: number) => fetchJson(`/articles/${id}/save`, { method: "POST" }),
  hide: (id: number) => fetchJson(`/articles/${id}/hide`, { method: "POST" }),
  like: (id: number) => fetchJson(`/articles/${id}/like`, { method: "POST" }),
  dismiss: (id: number) => fetchJson(`/articles/${id}/dismiss`, { method: "POST" }),
  reloadConfig: () => fetchJson<{ categories: string[] }>("/admin/reload-config", { method: "POST" }),
  systemResources: () => fetchJson<SystemStats>("/system/resources"),
  createCategory: (c: CategoryConfig) =>
    fetchJson("/categories", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(c),
    }),
  updateCategory: (id: string, c: CategoryConfig) =>
    fetchJson(`/categories/${encodeURIComponent(id)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(c),
    }),
  deleteCategory: (id: string) =>
    fetchJson(`/categories/${encodeURIComponent(id)}`, { method: "DELETE" }),
  llamaControl: (role: "standard" | "deep", action: "start" | "stop" | "restart") =>
    fetchJson<{ status: string }>(`/llama/${role}/${action}`, { method: "POST" }),
  getModels: () => fetchJson<ModelInfo[]>("/models"),
  getSettings: () => fetchJson<AppSettings>("/settings"),
  putSettings: (s: Partial<AppSettings>) =>
    fetchJson<AppSettings>("/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(s),
    }),
};

/** SSE 購読。切断時は EventSource が自動再接続する。 */
export function openEvents(onEvent: (ev: SseEvent) => void, onStateChange: (ok: boolean) => void) {
  const es = new EventSource(`${API_BASE}/events`);
  es.onopen = () => onStateChange(true);
  es.onerror = () => onStateChange(false);
  es.onmessage = (msg) => {
    try {
      onEvent(JSON.parse(msg.data) as SseEvent);
    } catch {
      // 不正なイベントは無視
    }
  };
  return es;
}

/** POST /chat の SSE ストリームを読み、イベントごとにコールバックする。 */
export async function chatStream(
  body: { messages: { role: string; content: string }[]; article_id?: number | null },
  onEvent: (ev: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${API_BASE}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok || !res.body) throw new Error(`${res.status} /chat`);
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const frame = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      for (const line of frame.split("\n")) {
        if (line.startsWith("data: ")) {
          try {
            onEvent(JSON.parse(line.slice(6)) as ChatEvent);
          } catch {
            // 不正なフレームは無視
          }
        }
      }
    }
  }
}

export function relativeTime(epoch: number): string {
  const sec = Math.max(0, Math.floor(Date.now() / 1000 - epoch));
  if (sec < 60) return "たった今";
  if (sec < 3600) return `${Math.floor(sec / 60)}分前`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}時間前`;
  return `${Math.floor(sec / 86400)}日前`;
}
