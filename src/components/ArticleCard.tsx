import type { Article } from "../types";
import { relativeTime } from "../api";

interface Props {
  article: Article;
  onSave: (id: number) => void;
  onHide: (id: number) => void;
  onOpen: (article: Article) => void;
}

export function ArticleCard({ article, onSave, onHide, onOpen }: Props) {
  const unread = article.status === "new";
  return (
    <div
      className={`card${unread ? " card-unread" : ""}`}
      onClick={() => onOpen(article)}
      title={article.title}
    >
      <div className="card-title">
        {unread && <span className="unread-dot" aria-label="未読" />}
        {article.title}
      </div>
      <div className="card-meta">
        <span className="card-source">{article.source ?? "-"}</span>
        <span className="card-time">{relativeTime(article.fetched_at)}</span>
        {article.impact && <span className={`impact impact-${article.impact}`}>{article.impact}</span>}
        {article.status === "saved" && <span className="badge-saved">保存済み</span>}
      </div>
      {article.tags && article.tags.length > 0 && (
        <div className="card-tags">
          {article.tags.slice(0, 4).map((t) => (
            <span key={t} className="tag">{t}</span>
          ))}
        </div>
      )}
      <div className="card-actions" onClick={(e) => e.stopPropagation()}>
        <button
          className="btn-icon"
          aria-label="保存"
          disabled={article.status === "saved"}
          onClick={() => onSave(article.id)}
        >
          保存
        </button>
        <button className="btn-icon btn-danger" aria-label="非表示" onClick={() => onHide(article.id)}>
          非表示
        </button>
      </div>
    </div>
  );
}
