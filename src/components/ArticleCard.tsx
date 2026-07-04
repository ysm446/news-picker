import type { Article } from "../types";
import { relativeTime } from "../api";
import { BookmarkIcon, ThumbsDownIcon, ThumbsUpIcon, XIcon } from "./icons";

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
      <div className="card-title">{displayTitle}</div>
      <div className="card-meta">
        {unread && <span className="unread-dot" aria-label="未読" />}
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
        {article.status === "saved" && (
          <span className="badge-saved" title="保存済み">
            <BookmarkIcon size={11} filled />
          </span>
        )}
        {article.rating === 1 && (
          <span className="badge-liked" title="良い記事と評価済み">
            <ThumbsUpIcon size={11} filled />
          </span>
        )}
        <div className="card-actions" onClick={(e) => e.stopPropagation()}>
          <button
            className="btn-icon card-action"
            aria-label="保存"
            title="保存 (パージ対象外になる)"
            disabled={article.status === "saved"}
            onClick={() => onSave(article.id)}
          >
            <BookmarkIcon filled={article.status === "saved"} />
          </button>
          <button
            className={`btn-icon card-action${article.rating === 1 ? " btn-liked" : ""}`}
            aria-label="良い記事"
            title="良い記事 (キュレーションの学習に使われる)"
            onClick={() => onLike(article.id)}
          >
            <ThumbsUpIcon filled={article.rating === 1} />
          </button>
          <button
            className="btn-icon card-action btn-danger"
            aria-label="興味なし"
            title="興味なし (非表示 + 学習の負例になる)"
            onClick={() => onDismiss(article.id)}
          >
            <ThumbsDownIcon />
          </button>
          <button
            className="btn-icon card-action btn-danger"
            aria-label="非表示"
            title="非表示のみ (学習には使われにくい)"
            onClick={() => onHide(article.id)}
          >
            <XIcon />
          </button>
        </div>
      </div>
      {article.tags && article.tags.length > 0 && (
        <div className="card-tags">
          {article.tags.slice(0, 3).map((t) => (
            <span key={t} className="tag">{t}</span>
          ))}
        </div>
      )}
    </div>
  );
}
