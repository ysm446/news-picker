import type { Article, CategoryInfo } from "../types";
import { ArticleCard } from "./ArticleCard";

interface Props {
  category: CategoryInfo;
  articles: Article[];
  brief: string | null;
  onSave: (id: number) => void;
  onHide: (id: number) => void;
  onOpen: (article: Article) => void;
  onSettings: (categoryId: string) => void;
}

function GearIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </svg>
  );
}

export function CategoryColumn({
  category, articles, brief, onSave, onHide, onOpen, onSettings,
}: Props) {
  const unread = articles.filter((a) => a.status === "new").length;
  return (
    <section className="column">
      <header className="column-header">
        <div className="column-title-row">
          <h2 className="column-title">{category.label}</h2>
          {unread > 0 && <span className="column-unread">{unread}</span>}
          <button
            className="column-settings"
            aria-label={`${category.label} の設定`}
            title="このカテゴリの設定"
            onClick={() => onSettings(category.id)}
          >
            <GearIcon />
          </button>
        </div>
        <p className="column-brief">{brief ?? "まだ要約はありません"}</p>
      </header>
      <div className="column-cards">
        {articles.length === 0 ? (
          <p className="column-empty">記事はまだありません</p>
        ) : (
          articles.map((a) => (
            <ArticleCard key={a.id} article={a} onSave={onSave} onHide={onHide} onOpen={onOpen} />
          ))
        )}
      </div>
    </section>
  );
}
