import DOMPurify from "dompurify";
import { marked } from "marked";

/** LLM 出力の Markdown を安全に描画する。リンクは OS ブラウザで開く。 */
export function Markdown({ text }: { text: string }) {
  const html = DOMPurify.sanitize(marked.parse(text, { async: false }) as string);
  return (
    <div
      className="chat-md"
      onClick={(e) => {
        const anchor = (e.target as HTMLElement).closest("a");
        if (anchor?.href) {
          e.preventDefault();
          window.open(anchor.href); // Electron 側で shell.openExternal に振られる
        }
      }}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}
