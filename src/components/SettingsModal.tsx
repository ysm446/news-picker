import { useEffect, useState } from "react";
import { api } from "../api";
import type { AppSettings, CategoryConfig, CategoryInfo, ModelInfo } from "../types";
import { XIcon } from "./icons";

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
  feeds: [],
  poll_interval_sec: 600,
  jitter_sec: 60,
  max_window: 30,
  summary_prompt: "",
  enabled: true,
};

export function SettingsModal({ categories, initialEditId, onClose, onChanged }: Props) {
  const initial = initialEditId ? categories.find((c) => c.id === initialEditId) : null;
  const [editing, setEditing] = useState<CategoryConfig | null>(initial ? { ...initial } : null);
  // 複数行/カンマ区切りの入力欄は生テキストで保持し、保存時にだけ配列へ変換する
  // (入力のたびに正規化すると改行やスペースが打てなくなるため)
  const [queryText, setQueryText] = useState(initial ? initial.query_templates.join("\n") : "");
  // feeds は後から追加したフィールドなので、旧バックエンドの応答 (undefined) にも耐える
  const [feedsText, setFeedsText] = useState(initial ? (initial.feeds ?? []).join("\n") : "");
  const [isNew, setIsNew] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<"categories" | "prefs">("categories");
  const [prefs, setPrefs] = useState<AppSettings | null>(null);
  const [savedPrefs, setSavedPrefs] = useState<AppSettings | null>(null);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [prefsSaved, setPrefsSaved] = useState(false);

  useEffect(() => {
    api.getSettings()
      .then((s) => {
        setPrefs(s);
        setSavedPrefs(s);
      })
      .catch((e) => setError(String(e)));
    api.getModels().then(setModels).catch(console.error);
  }, []);

  const savePrefs = async () => {
    if (!prefs) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await api.putSettings(prefs);
      // モデルが変わった役割は再起動して反映 (deep は停止中なら停止のまま)
      if (savedPrefs && updated.model_standard !== savedPrefs.model_standard) {
        await api.llamaControl("standard", "restart");
      }
      if (savedPrefs && updated.model_deep !== savedPrefs.model_deep) {
        await api.llamaControl("deep", "restart");
      }
      setPrefs(updated);
      setSavedPrefs(updated);
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
    setFeedsText("");
    setIsNew(true);
    setError(null);
  };

  const startEdit = (c: CategoryInfo) => {
    setEditing({ ...c });
    setQueryText(c.query_templates.join("\n"));
    setFeedsText((c.feeds ?? []).join("\n"));
    setIsNew(false);
    setError(null);
  };

  const save = async () => {
    if (!editing) return;
    setBusy(true);
    setError(null);
    // impact_axis は UI からは編集不可の廃止項目だが、...editing 経由で
    // 既存値をそのまま送り返す (yaml 上の値を勝手に消さない)
    const payload: CategoryConfig = {
      ...editing,
      query_templates: queryText.split("\n").map((s) => s.trim()).filter(Boolean),
      feeds: feedsText.split("\n").map((s) => s.trim()).filter(Boolean),
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

  const navTo = (t: "categories" | "prefs") => {
    setTab(t);
    setEditing(null);
    setError(null);
  };

  const contentTitle =
    tab === "prefs"
      ? "環境設定"
      : editing !== null
        ? isNew
          ? "カテゴリを追加"
          : `カテゴリ: ${editing.label || editing.id}`
        : "カテゴリ";

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal modal-settings" onClick={(e) => e.stopPropagation()}>
        <aside className="settings-nav">
          <p className="settings-nav-title">設定</p>
          <button
            className={`settings-nav-item${tab === "categories" ? " settings-nav-item-active" : ""}`}
            onClick={() => navTo("categories")}
          >
            カテゴリ
          </button>
          <button
            className={`settings-nav-item${tab === "prefs" ? " settings-nav-item-active" : ""}`}
            onClick={() => navTo("prefs")}
          >
            環境設定
          </button>
        </aside>
        <div className="settings-content">
        <header className="modal-header">
          <h2>{contentTitle}</h2>
          <button className="btn-icon icon-btn" aria-label="閉じる" title="閉じる" onClick={onClose}>
            <XIcon />
          </button>
        </header>

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
                  <label className="filter-check prefs-check">
                    <input
                      type="checkbox"
                      checked={prefs.show_thumbnails}
                      onChange={(e) =>
                        setPrefs({ ...prefs, show_thumbnails: e.target.checked })
                      }
                    />
                    カードにサムネイル画像を表示する (画像は data/cache/images/
                    に一時保存され、記事の整理と一緒に削除)
                  </label>
                  <label className="form-row">
                    <span>常駐モデル (要約・採点・チャット代行。変更は保存時に再起動)</span>
                    <select
                      value={prefs.model_standard}
                      onChange={(e) => setPrefs({ ...prefs, model_standard: e.target.value })}
                    >
                      {models.map((m) => (
                        <option key={m.path} value={m.path}>
                          {m.path} ({m.size_gb} GB)
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="form-row">
                    <span>深堀りモデル (チャット用。ステータスバーからロード/アンロード)</span>
                    <select
                      value={prefs.model_deep}
                      onChange={(e) => setPrefs({ ...prefs, model_deep: e.target.value })}
                    >
                      {models.map((m) => (
                        <option key={m.path} value={m.path}>
                          {m.path} ({m.size_gb} GB)
                        </option>
                      ))}
                    </select>
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
              <label className="form-row">
                <span>RSS/Atom フィード (任意。1行1URL。検索と併用可)</span>
                <textarea
                  rows={2}
                  value={feedsText}
                  placeholder={"https://github.com/ggml-org/llama.cpp/releases.atom"}
                  onChange={(e) => setFeedsText(e.target.value)}
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
                disabled={
                  busy ||
                  !editing.id ||
                  !editing.label ||
                  (queryText.trim() === "" && feedsText.trim() === "")
                }
                onClick={() => void save()}
              >
                {isNew ? "追加" : "保存"}
              </button>
            </footer>
          </>
        )}
        </div>
      </div>
    </div>
  );
}
