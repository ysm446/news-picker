import type { Article } from "../types";
import { relativeTime } from "../api";

interface Props {
  article: Article | null;
  loading: boolean;
  error: string | null;
  onClose: () => void;
  onDeepDive: (article: Article) => void;
}

export function DetailPanel({ article, loading, error, onClose, onDeepDive }: Props) {
  if (!article) return null;
  const enriched = article.enriched_at != null;
  return (
    <aside className="detail-panel">
      <header className="detail-header">
        <span className="detail-time">{relativeTime(article.fetched_at)}</span>
        <button className="btn-icon" onClick={onClose} aria-label="閉じる">
          閉じる
        </button>
      </header>
      <div className="detail-body">
        <h2 className="detail-title">{article.title}</h2>
        <div className="detail-meta">
          <span>{article.source ?? "-"}</span>
          {article.impact && (
            <span className={`impact impact-${article.impact}`}>{article.impact}</span>
          )}
        </div>

        {error && <p className="detail-error">生成に失敗しました: {error}</p>}
        {!enriched && loading && !error && (
          <p className="detail-loading">要約を生成中...(9B)</p>
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
