import { useState } from "react";
import { api } from "../api";
import type { CategoryConfig, CategoryInfo } from "../types";

interface Props {
  categories: CategoryInfo[];
  initialEditId?: string | null; // 指定時はそのカテゴリの編集画面を直接開く
  onClose: () => void;
  onChanged: () => void;
}

const EMPTY: CategoryConfig = {
  id: "",
  label: "",
  keywords: [],
  query_templates: [],
  poll_interval_sec: 600,
  jitter_sec: 60,
  impact_axis: ["notable", "minor"],
  max_window: 30,
  summary_prompt: "",
};

export function SettingsModal({ categories, initialEditId, onClose, onChanged }: Props) {
  const [editing, setEditing] = useState<CategoryConfig | null>(() => {
    const target = initialEditId ? categories.find((c) => c.id === initialEditId) : null;
    return target ? { ...target } : null;
  });
  const [isNew, setIsNew] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const startNew = () => {
    setEditing({ ...EMPTY });
    setIsNew(true);
    setError(null);
  };

  const startEdit = (c: CategoryInfo) => {
    setEditing({ ...c });
    setIsNew(false);
    setError(null);
  };

  const save = async () => {
    if (!editing) return;
    setBusy(true);
    setError(null);
    try {
      if (isNew) {
        await api.createCategory(editing);
      } else {
        await api.updateCategory(editing.id, editing);
      }
      setEditing(null);
      onChanged();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (c: CategoryInfo) => {
    if (!window.confirm(`カテゴリ「${c.label}」を削除しますか?\n(記事データは残ります。再作成すれば再び表示されます)`)) {
      return;
    }
    setBusy(true);
    try {
      await api.deleteCategory(c.id);
      onChanged();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <header className="modal-header">
          <h2>カテゴリ設定</h2>
          <button className="btn-icon" onClick={onClose}>閉じる</button>
        </header>

        {error && <p className="detail-error">{error}</p>}

        {editing === null ? (
          <>
            <div className="settings-list">
              {categories.map((c) => (
                <div key={c.id} className="settings-row">
                  <div className="settings-row-main">
                    <span className="settings-label">{c.label}</span>
                    <span className="settings-id">{c.id}</span>
                    <span className="settings-meta">{c.poll_interval_sec}秒毎</span>
                  </div>
                  <div className="settings-row-actions">
                    <button className="btn-icon" onClick={() => startEdit(c)}>編集</button>
                    <button className="btn-icon btn-danger" disabled={busy} onClick={() => void remove(c)}>
                      削除
                    </button>
                  </div>
                </div>
              ))}
            </div>
            <footer className="modal-footer">
              <button className="btn-primary" onClick={startNew}>カテゴリを追加</button>
            </footer>
          </>
        ) : (
          <>
            <div className="settings-form">
              <label className="form-row">
                <span>ID (小文字英数字とハイフン、変更不可)</span>
                <input
                  value={editing.id}
                  disabled={!isNew}
                  placeholder="memory-chips"
                  onChange={(e) => setEditing({ ...editing, id: e.target.value })}
                />
              </label>
              <label className="form-row">
                <span>表示名</span>
                <input
                  value={editing.label}
                  placeholder="メモリ半導体"
                  onChange={(e) => setEditing({ ...editing, label: e.target.value })}
                />
              </label>
              <label className="form-row">
                <span>検索クエリ (1行1クエリ。{"{month}"} は現在の年月に展開)</span>
                <textarea
                  rows={4}
                  value={editing.query_templates.join("\n")}
                  placeholder={"HBM 需給 {month}\nDRAM 価格"}
                  onChange={(e) =>
                    setEditing({
                      ...editing,
                      query_templates: e.target.value.split("\n").map((s) => s.trim()).filter(Boolean),
                    })
                  }
                />
              </label>
              <div className="form-grid">
                <label className="form-row">
                  <span>取得間隔 (秒)</span>
                  <input
                    type="number"
                    min={60}
                    value={editing.poll_interval_sec}
                    onChange={(e) =>
                      setEditing({ ...editing, poll_interval_sec: Number(e.target.value) || 600 })
                    }
                  />
                </label>
                <label className="form-row">
                  <span>要約対象の記事数</span>
                  <input
                    type="number"
                    min={5}
                    value={editing.max_window}
                    onChange={(e) =>
                      setEditing({ ...editing, max_window: Number(e.target.value) || 30 })
                    }
                  />
                </label>
              </div>
              <label className="form-row">
                <span>impact の選択肢 (カンマ区切り)</span>
                <input
                  value={editing.impact_axis.join(", ")}
                  placeholder="bullish, neutral, bearish"
                  onChange={(e) =>
                    setEditing({
                      ...editing,
                      impact_axis: e.target.value.split(",").map((s) => s.trim()).filter(Boolean),
                    })
                  }
                />
              </label>
              <label className="form-row">
                <span>カテゴリ要約のプロンプト (任意)</span>
                <textarea
                  rows={3}
                  value={editing.summary_prompt}
                  placeholder="あなたは◯◯アナリスト。直近記事から重要な動きを3〜5行で要約せよ。"
                  onChange={(e) => setEditing({ ...editing, summary_prompt: e.target.value })}
                />
              </label>
            </div>
            <footer className="modal-footer">
              <button className="btn-icon" onClick={() => setEditing(null)}>キャンセル</button>
              <button
                className="btn-primary"
                disabled={busy || !editing.id || !editing.label || editing.query_templates.length === 0}
                onClick={() => void save()}
              >
                {isNew ? "追加" : "保存"}
              </button>
            </footer>
          </>
        )}
      </div>
    </div>
  );
}
