import type { Article } from "../types";
import { relativeTime } from "../api";

interface Props {
  article: Article;
  translate: boolean;
  onSave: (id: number) => void;
  onHide: (id: number) => void;
  onLike: (id: number) => void;
  onDismiss: (id: number) => void;
  onOpen: (article: Article) => void;
}

export function ArticleCard({
  article, translate, onSave, onHide, onLike, onDismiss, onOpen,
}: Props) {
  const unread = article.status === "new";
  const displayTitle = translate && article.title_ja ? article.title_ja : article.title;
  return (
    <div
      className={`card${unread ? " card-unread" : ""}`}
      onClick={() => onOpen(article)}
      title={article.title /* ツールチップは常に原文 */}
    >
      <div className="card-title">
        {unread && <span className="unread-dot" aria-label="未読" />}
        {displayTitle}
      </div>
      <div className="card-meta">
        <span className="card-source">{article.source ?? "-"}</span>
        <span className="card-time">{relativeTime(article.fetched_at)}</span>
        {article.relevance !== null && (
          <span
            className={`card-relevance${article.relevance < 50 ? " card-relevance-low" : ""}`}
            title={`関連度 ${article.relevance} (9B 自動採点)`}
          >
            {article.relevance}
          </span>
        )}
        {article.impact && <span className={`impact impact-${article.impact}`}>{article.impact}</span>}
        {article.status === "saved" && <span className="badge-saved">保存済み</span>}
        {article.rating === 1 && <span className="badge-liked" title="👍 評価済み">👍</span>}
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
        <button
          className={`btn-icon${article.rating === 1 ? " btn-liked" : ""}`}
          aria-label="良い記事"
          title="良い記事 (キュレーションの学習に使われる)"
          onClick={() => onLike(article.id)}
        >
          👍
        </button>
        <button
          className="btn-icon btn-danger"
          aria-label="興味なし"
          title="興味なし (非表示 + 学習の負例になる)"
          onClick={() => onDismiss(article.id)}
        >
          興味なし
        </button>
        <button
          className="btn-icon btn-danger"
          aria-label="非表示"
          title="非表示のみ (学習には使われにくい)"
          onClick={() => onHide(article.id)}
        >
          ✕
        </button>
      </div>
    </div>
  );
}
