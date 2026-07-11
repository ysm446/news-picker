import { useState } from "react";
import type { Article } from "../types";
import { API_BASE, relativeTime } from "../api";
import { BookmarkIcon, ThumbsDownIcon, ThumbsUpIcon } from "./icons";

interface Props {
  article: Article | null;
  loading: boolean;
  error: string | null;
  translate: boolean;
  showThumbnails: boolean;
  besideChat: boolean; // 深堀りチャットと併存中はチャットの左に並ぶ
  onClose: () => void;
  onDeepDive: (article: Article) => void;
  onSave: (id: number) => void;
  onLike: (id: number) => void;
  onDismiss: (id: number) => void;
}

export function DetailPanel({
  article, loading, error, translate, showThumbnails, besideChat,
  onClose, onDeepDive, onSave, onLike, onDismiss,
}: Props) {
  // 取得失敗した記事の画像だけ隠す (記事を切り替えたらまた試す)
  const [brokenImageId, setBrokenImageId] = useState<number | null>(null);
  if (!article) return null;
  const enriched = article.enriched_at != null;
  const saved = article.status === "saved";
  const translated = translate && article.title_ja && article.title_ja !== article.title;
  return (
    <aside className={`detail-panel${besideChat ? " detail-panel-shifted" : ""}`}>
      <header className="detail-header">
        <button className="btn-icon detail-close" onClick={onClose} aria-label="閉じる">
          閉じる
        </button>
      </header>
      <div className="detail-body">
        {showThumbnails && article.image_url && brokenImageId !== article.id && (
          <img
            className="detail-image"
            src={`${API_BASE}/articles/${article.id}/thumb`}
            alt=""
            onError={() => setBrokenImageId(article.id)}
          />
        )}
        <h2 className="detail-title">{translated ? article.title_ja : article.title}</h2>
        {translated && <p className="detail-original">{article.title}</p>}
        <div className="detail-meta">
          <span>{article.source ?? "-"}</span>
          <span className="detail-time">{relativeTime(article.fetched_at)}</span>
          <div className="detail-actions">
            <button
              className={`btn-icon card-action${saved ? " btn-saved" : ""}`}
              aria-label={saved ? "保存を解除" : "保存"}
              title={saved ? "保存を解除 (自動整理の対象に戻る)" : "保存 (パージ対象外になる)"}
              onClick={() => onSave(article.id)}
            >
              <BookmarkIcon filled={saved} />
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
          </div>
        </div>

        {error && <p className="detail-error">生成に失敗しました: {error}</p>}

        {/* 生成待ちの間も取得済みの情報 (検索時の抜粋) を先に読めるようにする */}
        {!enriched && article.snippet && (
          <section className="detail-section">
            <h3>抜粋 (検索結果より)</h3>
            <p>{article.snippet}</p>
          </section>
        )}
        {!enriched && loading && !error && (
          <section className="detail-section" aria-busy="true">
            <h3>
              要約<span className="detail-generating">生成中...</span>
            </h3>
            <div className="skeleton-line" />
            <div className="skeleton-line" />
            <div className="skeleton-line skeleton-line-short" />
          </section>
        )}

        {enriched && (
          <>
            <section className="detail-section">
              <h3>要約</h3>
              <p>{article.summary}</p>
            </section>
            {article.key_points && article.key_points.length > 0 && (
              <section className="detail-section">
                <h3>要点</h3>
                <ul>
                  {article.key_points.map((p, i) => (
                    <li key={i}>{p}</li>
                  ))}
                </ul>
              </section>
            )}
            {article.entities &&
              (article.entities.tickers.length > 0 || article.entities.companies.length > 0) && (
                <section className="detail-section">
                  <h3>エンティティ</h3>
                  <div className="card-tags">
                    {article.entities.tickers.map((t) => (
                      <span key={`t-${t}`} className="tag tag-ticker">{t}</span>
                    ))}
                    {article.entities.companies.map((c) => (
                      <span key={`c-${c}`} className="tag">{c}</span>
                    ))}
                  </div>
                </section>
              )}
            {article.tags && article.tags.length > 0 && (
              <section className="detail-section">
                <h3>タグ</h3>
                <div className="card-tags">
                  {article.tags.map((t) => (
                    <span key={t} className="tag">{t}</span>
                  ))}
                </div>
              </section>
            )}
          </>
        )}

        <section className="detail-section">
          <h3>出典</h3>
          <a href={article.url} target="_blank" rel="noreferrer" className="detail-link">
            {article.url}
          </a>
        </section>
      </div>
      <footer className="detail-footer">
        <button className="btn-primary" onClick={() => onDeepDive(article)}>
          このニュースを深堀り
        </button>
      </footer>
    </aside>
  );
}
