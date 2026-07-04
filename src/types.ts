export interface CategoryConfig {
  id: string;
  label: string;
  keywords: string[];
  query_templates: string[];
  poll_interval_sec: number;
  jitter_sec: number;
  impact_axis: string[];
  max_window: number;
  summary_prompt: string;
}

export interface CategoryInfo extends CategoryConfig {
  unread: number;
}

export interface Entities {
  tickers: string[];
  companies: string[];
  models: string[];
}

export interface Article {
  id: number;
  category: string;
  title: string;
  url: string;
  source: string | null;
  snippet: string | null;
  status: "new" | "seen" | "saved" | "hidden";
  fetched_at: number;
  published_at: number | null;
  summary: string | null;
  key_points: string[] | null;
  entities: Entities | null;
  impact: string | null;
  tags: string[] | null;
  enriched_at: number | null;
}

export interface Brief {
  category: string;
  brief: string;
  article_count: number;
  updated_at: number;
}

export type SseEvent =
  | {
      type: "article.new";
      category: string;
      article: { id: number; title: string; source: string | null; fetched_at: number };
    }
  | { type: "article.enriched"; article: Partial<Article> & { id: number } }
  | { type: "article.enrich_failed"; id: number; detail: string }
  | { type: "article.status_changed"; id: number; status: Article["status"] }
  | { type: "category.brief_updated"; category: string; brief: string; updated_at: number };

export type ChatEvent =
  | { type: "chat.thinking"; text: string }
  | { type: "chat.tool_call"; name: string; args: { query?: string } }
  | { type: "chat.tool_result"; name: string; count: number | null }
  | { type: "chat.answer"; content: string }
  | { type: "chat.error"; detail: string }
  | { type: "chat.done" };

export interface ChatTurn {
  role: "user" | "assistant";
  content: string;
  thinking?: string;
  activity?: string[];
}

export interface GpuStats {
  name: string;
  gpu_percent: number;
  vram_used_gb: number;
  vram_total_gb: number;
  vram_percent: number;
}

export interface SystemStats {
  cpu_percent: number;
  ram_used_gb: number;
  ram_total_gb: number;
  ram_percent: number;
  gpus: GpuStats[];
  llama: { "9b": boolean; "35b": boolean };
}
