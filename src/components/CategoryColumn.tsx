import { useState } from "react";
import type { Article, CategoryInfo } from "../types";
import { api } from "../api";
import { ArticleCard } from "./ArticleCard";
import { GearIcon, RefreshIcon } from "./icons";

interface Props {
  category: CategoryInfo;
  articles: Article[];
  brief: string | null;
  translate: boolean;
  showThumbnails: boolean;
  onSave: (id: number) => void;
  onHide: (id: number) => void;
  onLike: (id: number) => void;
  onDismiss: (id: number) => void;
  onOpen: (article: Article) => void;
  onSettings: (categoryId: string) => void;
}

export function CategoryColumn({
  category, articles, brief, translate, showThumbnails,
  onSave, onHide, onLike, onDismiss, onOpen, onSettings,
}: Props) {
  const unread = articles.filter((a) => a.status === "new").length;
  const [briefOpen, setBriefOpen] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  const refresh = () => {
    setRefreshing(true);
    // 新着はポーリングと同じく SSE (article.new / article.curated) で流れ込む
    api.ingestNow(category.id)
      .catch(console.error)
      .finally(() => setRefreshing(false));
  };

  return (
    <section className="column">
      <header className="column-header">
        <div className="column-title-row">
          <h2 className="column-title">{category.label}</h2>
          {unread > 0 && <span className="column-unread">{unread}</span>}
          <button
            className={`column-settings column-refresh${refreshing ? " column-refresh-busy" : ""}`}
            aria-label={`${category.label} を今すぐ更新`}
            title={refreshing ? "取り込み中..." : "今すぐ更新 (検索 / RSS を即時実行)"}
            disabled={refreshing}
            onClick={refresh}
          >
            <RefreshIcon />
          </button>
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
              showThumbnails={showThumbnails}
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
