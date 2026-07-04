import { useEffect, useState } from "react";
import { api } from "../api";
import type { AppSettings, CategoryConfig, CategoryInfo } from "../types";

interface Props {
  categories: CategoryInfo[];
  initialEditId?: string | null; // 指定時はそのカテゴリの編集画面を直接開く
  onClose: () => void;
  onChanged: () => void;
}

const EMPTY: CategoryConfig = {
  id: "",
  label: "",
  description: "",
  keywords: [],
  query_templates: [],
  poll_interval_sec: 600,
  jitter_sec: 60,
  impact_axis: ["notable", "minor"],
  max_window: 30,
  summary_prompt: "",
};

export function SettingsModal({ categories, initialEditId, onClose, onChanged }: Props) {
  const initial = initialEditId ? categories.find((c) => c.id === initialEditId) : null;
  const [editing, setEditing] = useState<CategoryConfig | null>(initial ? { ...initial } : null);
  // 複数行/カンマ区切りの入力欄は生テキストで保持し、保存時にだけ配列へ変換する
  // (入力のたびに正規化すると改行やスペースが打てなくなるため)
  const [queryText, setQueryText] = useState(initial ? initial.query_templates.join("\n") : "");
  const [impactText, setImpactText] = useState(initial ? initial.impact_axis.join(", ") : "");
  const [isNew, setIsNew] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<"categories" | "prefs">("categories");
  const [prefs, setPrefs] = useState<AppSettings | null>(null);
  const [prefsSaved, setPrefsSaved] = useState(false);

  useEffect(() => {
    api.getSettings().then(setPrefs).catch((e) => setError(String(e)));
  }, []);

  const savePrefs = async () => {
    if (!prefs) return;
    setBusy(true);
    setError(null);
    try {
      setPrefs(await api.putSettings(prefs));
      setPrefsSaved(true);
      setTimeout(() => setPrefsSaved(false), 2000);
      onChanged();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const startNew = () => {
    setEditing({ ...EMPTY });
    setQueryText("");
    setImpactText(EMPTY.impact_axis.join(", "));
    setIsNew(true);
    setError(null);
  };

  const startEdit = (c: CategoryInfo) => {
    setEditing({ ...c });
    setQueryText(c.query_templates.join("\n"));
    setImpactText(c.impact_axis.join(", "));
    setIsNew(false);
    setError(null);
  };

  const save = async () => {
    if (!editing) return;
    setBusy(true);
    setError(null);
    const payload: CategoryConfig = {
      ...editing,
      query_templates: queryText.split("\n").map((s) => s.trim()).filter(Boolean),
      impact_axis: impactText.split(",").map((s) => s.trim()).filter(Boolean),
    };
    try {
      if (isNew) {
        await api.createCategory(payload);
      } else {
        await api.updateCategory(payload.id, payload);
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
          <h2>設定</h2>
          <button className="btn-icon" onClick={onClose}>閉じる</button>
        </header>

        {editing === null && (
          <div className="modal-tabs">
            <button
              className={`modal-tab${tab === "categories" ? " modal-tab-active" : ""}`}
              onClick={() => setTab("categories")}
            >
              カテゴリ
            </button>
            <button
              className={`modal-tab${tab === "prefs" ? " modal-tab-active" : ""}`}
              onClick={() => setTab("prefs")}
            >
              環境設定
            </button>
          </div>
        )}

        {error && <p className="detail-error">{error}</p>}

        {editing === null && tab === "prefs" ? (
          <>
            <div className="settings-form">
              {prefs === null ? (
                <p className="chat-hint">読み込み中...</p>
              ) : (
                <>
                  <label className="filter-check prefs-check">
                    <input
                      type="checkbox"
                      checked={prefs.translate_titles}
                      onChange={(e) =>
                        setPrefs({ ...prefs, translate_titles: e.target.checked })
                      }
                    />
                    ニュースの見出しを日本語訳する (9B が自動翻訳。新着から適用。
                    既存分は採点し直しで翻訳)
                  </label>
                  <div className="form-grid">
                    <label className="form-row">
                      <span>ノイズ閾値 (関連度がこれ未満を非表示。0-100)</span>
                      <input
                        type="number"
                        min={0}
                        max={100}
                        value={prefs.noise_threshold}
                        onChange={(e) =>
                          setPrefs({ ...prefs, noise_threshold: Number(e.target.value) || 0 })
                        }
                      />
                    </label>
                    <label className="form-row">
                      <span>記事の保持日数 (保存済みは対象外)</span>
                      <input
                        type="number"
                        min={1}
                        max={365}
                        value={prefs.retention_days}
                        onChange={(e) =>
                          setPrefs({ ...prefs, retention_days: Number(e.target.value) || 14 })
                        }
                      />
                    </label>
                  </div>
                </>
              )}
            </div>
            <footer className="modal-footer">
              {prefsSaved && <span className="prefs-saved">保存しました</span>}
              <button
                className="btn-primary"
                disabled={busy || prefs === null}
                onClick={() => void savePrefs()}
              >
                保存
              </button>
            </footer>
          </>
        ) : editing === null ? (
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
                <span>説明・採点基準 (任意。キュレーションの関連度判定に使われる)</span>
                <textarea
                  rows={2}
                  value={editing.description}
                  placeholder="例: オープンモデル限定。クローズドな商用サービスの話題は関連度を低く"
                  onChange={(e) => setEditing({ ...editing, description: e.target.value })}
                />
              </label>
              <label className="form-row">
                <span>検索クエリ (1行1クエリ。{"{month}"} は現在の年月に展開)</span>
                <textarea
                  rows={4}
                  value={queryText}
                  placeholder={"HBM 需給 {month}\nDRAM 価格"}
                  onChange={(e) => setQueryText(e.target.value)}
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
                  value={impactText}
                  placeholder="bullish, neutral, bearish"
                  onChange={(e) => setImpactText(e.target.value)}
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
                disabled={busy || !editing.id || !editing.label || queryText.trim() === ""}
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
