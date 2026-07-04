export interface CategoryInfo {
  id: string;
  label: string;
  poll_interval_sec: number;
  impact_axis: string[];
  unread: number;
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
  impact: string | null;
  tags: string[] | null;
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
  | { type: "article.status_changed"; id: number; status: Article["status"] }
  | { type: "category.brief_updated"; category: string; brief: string; updated_at: number };
