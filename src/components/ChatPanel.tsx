import { useCallback, useEffect, useRef, useState } from "react";
import { chatStream } from "../api";
import type { ChatEvent, ChatTurn } from "../types";

interface Props {
  articleId: number | null;
  articleTitle: string | null;
  onClose: () => void;
}

export function ChatPanel({ articleId, articleTitle, onClose }: Props) {
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [activity, setActivity] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [currentModel, setCurrentModel] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const thinkingRef = useRef<string>("");
  const activityRef = useRef<string[]>([]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [turns, activity]);

  const send = useCallback(() => {
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    setError(null);
    setBusy(true);
    thinkingRef.current = "";
    activityRef.current = [];
    setActivity([]);

    const history = [...turns, { role: "user" as const, content: text }];
    setTurns(history);

    const onEvent = (ev: ChatEvent) => {
      if (ev.type === "chat.model") {
        setCurrentModel(ev.model);
        const line =
          ev.role === "deep"
            ? `モデル: ${ev.model}`
            : `モデル: ${ev.model} (深堀りモデルはオフ)`;
        activityRef.current = [...activityRef.current, line];
        setActivity(activityRef.current);
      } else if (ev.type === "chat.thinking") {
        thinkingRef.current += (thinkingRef.current ? "\n\n" : "") + ev.text;
      } else if (ev.type === "chat.tool_call") {
        const line = `${ev.name}(${ev.args.query ?? ""})`;
        activityRef.current = [...activityRef.current, line];
        setActivity(activityRef.current);
      } else if (ev.type === "chat.tool_result") {
        const last = activityRef.current.length - 1;
        if (last >= 0) {
          activityRef.current = [
            ...activityRef.current.slice(0, last),
            `${activityRef.current[last]} → ${ev.count ?? "?"}件`,
          ];
          setActivity(activityRef.current);
        }
      } else if (ev.type === "chat.answer") {
        setTurns((prev) => [
          ...prev,
          {
            role: "assistant",
            content: ev.content,
            thinking: thinkingRef.current || undefined,
            activity: activityRef.current.length ? activityRef.current : undefined,
          },
        ]);
        setActivity([]);
      } else if (ev.type === "chat.error") {
        setError(ev.detail);
      } else if (ev.type === "chat.done") {
        setBusy(false);
      }
    };

    chatStream(
      { messages: history.map(({ role, content }) => ({ role, content })), article_id: articleId },
      onEvent,
    ).catch((e) => {
      setError(String(e));
      setBusy(false);
    });
  }, [input, busy, turns, articleId]);

  return (
    <aside className="chat-panel">
      <header className="detail-header">
        <div className="chat-context">
          {articleTitle ? `深堀り: ${articleTitle}` : "Vault 横断チャット"}
        </div>
        <button className="btn-icon" onClick={onClose} aria-label="閉じる">
          閉じる
        </button>
      </header>
      <div className="chat-messages" ref={scrollRef}>
        {turns.length === 0 && (
          <p className="chat-hint">
            記事庫と Web を検索しながら回答します。
            {articleTitle ? "この記事について聞いてください。" : "何でも聞いてください。"}
          </p>
        )}
        {turns.map((t, i) =>
          t.role === "user" ? (
            <div key={i} className="chat-user">{t.content}</div>
          ) : (
            <div key={i} className="chat-assistant">
              {t.activity && (
                <div className="chat-activity">
                  {t.activity.map((a, j) => (
                    <div key={j}>{a}</div>
                  ))}
                </div>
              )}
              {t.thinking && (
                <details className="chat-thinking">
                  <summary>思考を表示</summary>
                  <pre>{t.thinking}</pre>
                </details>
              )}
              <div className="chat-content">{t.content}</div>
            </div>
          ),
        )}
        {busy && (
          <div className="chat-assistant">
            <div className="chat-activity">
              {activity.map((a, j) => (
                <div key={j}>{a}</div>
              ))}
              <div className="chat-busy">
                回答を生成中...{currentModel ? `(${currentModel})` : ""}
              </div>
            </div>
          </div>
        )}
        {error && <p className="detail-error">{error}</p>}
      </div>
      <footer className="chat-input-row">
        <textarea
          className="chat-input"
          value={input}
          rows={2}
          placeholder="質問を入力 (Enter で送信 / Shift+Enter で改行)"
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              send();
            }
          }}
        />
        <button className="btn-primary chat-send" onClick={send} disabled={busy || !input.trim()}>
          送信
        </button>
      </footer>
    </aside>
  );
}
