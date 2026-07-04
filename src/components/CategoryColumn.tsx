import { useState } from "react";
import type { Article, CategoryInfo } from "../types";
import { ArticleCard } from "./ArticleCard";
import { GearIcon } from "./icons";

interface Props {
  category: CategoryInfo;
  articles: Article[];
  brief: string | null;
  translate: boolean;
  onSave: (id: number) => void;
  onHide: (id: number) => void;
  onLike: (id: number) => void;
  onDismiss: (id: number) => void;
  onOpen: (article: Article) => void;
  onSettings: (categoryId: string) => void;
}

export function CategoryColumn({
  category, articles, brief, translate, onSave, onHide, onLike, onDismiss, onOpen, onSettings,
}: Props) {
  const unread = articles.filter((a) => a.status === "new").length;
  const [briefOpen, setBriefOpen] = useState(false);
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
        <p
          className={`column-brief${briefOpen ? " column-brief-open" : ""}`}
          title={briefOpen ? "クリックで折りたたむ" : "クリックで全文表示"}
          onClick={() => setBriefOpen((prev) => !prev)}
        >
          {brief ?? "まだ要約はありません"}
        </p>
      </header>
      <div className="column-cards">
        {articles.length === 0 ? (
          <p className="column-empty">記事はまだありません</p>
        ) : (
          articles.map((a) => (
            <ArticleCard
              key={a.id}
              article={a}
              translate={translate}
              onSave={onSave}
              onHide={onHide}
              onLike={onLike}
              onDismiss={onDismiss}
              onOpen={onOpen}
            />
          ))
        )}
      </div>
    </section>
  );
}
