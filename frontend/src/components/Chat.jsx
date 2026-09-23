import { useEffect, useRef, useState } from "react";
import { Bot, Send, UserRound, GripVertical } from "lucide-react";
import { askQuestion } from "../api";

function cleanText(text = "") {
  return text
    // Remove escaped Markdown characters produced by some model responses.
    .replace(/\\([*_`#])/g, "$1")
    // Headings: ## Title -> Title
    .replace(/^\s{0,3}#{1,6}\s*/gm, "")
    // Bold / italic / inline-code markers.
    .replace(/\*\*(.*?)\*\*/gs, "$1")
    .replace(/__(.*?)__/gs, "$1")
    .replace(/(?<!\w)\*(.*?)\*(?!\w)/gs, "$1")
    .replace(/(?<!\w)_(.*?)_(?!\w)/gs, "$1")
    .replace(/`([^`]+)`/g, "$1")
    // Markdown table separators.
    .replace(/^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$/gm, "")
    // Make table rows readable instead of showing pipes.
    .replace(/^\s*\|(.+)\|\s*$/gm, (_, row) =>
      row
        .split("|")
        .map((cell) => cell.trim())
        .filter(Boolean)
        .join("  •  ")
    )
    // Normalize Markdown bullets.
    .replace(/^\s*[-*+]\s+/gm, "• ")
    // Remove accidental escaped punctuation.
    .replace(/\\([[\](){}])/g, "$1")
    // Collapse excessive blank lines.
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

export default function Chat({ repoId }) {
  const [messages, setMessages] = useState([
    {
      role: "assistant",
      text: "Ask me about the repository structure, files, dependencies, or implementation.",
    },
  ]);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [height, setHeight] = useState(607);

  const resizing = useRef(false);
  const messagesEnd = useRef(null);

  useEffect(() => {
    messagesEnd.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    function onMove(event) {
      if (!resizing.current) return;

      const chat = document.querySelector(".chat");
      if (!chat) return;

      const rect = chat.getBoundingClientRect();
      const nextHeight = Math.max(
        380,
        Math.min(850, event.clientY - rect.top)
      );

      setHeight(nextHeight);
    }

    function onUp() {
      resizing.current = false;
      document.body.style.userSelect = "";
      document.body.style.cursor = "";
    }

    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);

    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
  }, []);

  function startResize(event) {
    event.preventDefault();
    resizing.current = true;
    document.body.style.userSelect = "none";
    document.body.style.cursor = "ns-resize";
  }

  async function submit(event) {
    event.preventDefault();

    const text = question.trim();

    if (!text || busy || !repoId) return;

    setQuestion("");

    setMessages((current) => [
      ...current,
      {
        role: "user",
        text,
      },
    ]);

    setBusy(true);

    try {
      const result = await askQuestion(repoId, text);

      setMessages((current) => [
        ...current,
        {
          role: "assistant",
          text: cleanText(result.answer || "No answer returned."),
          sources: result.sources || [],
        },
      ]);
    } catch (error) {
      setMessages((current) => [
        ...current,
        {
          role: "assistant",
          text:
            error?.response?.data?.detail ||
            "Something went wrong while asking the repository assistant.",
        },
      ]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section
      className="panel chat"
      style={{ height: `${height}px` }}
    >
      <div
        className="chat-resize-handle"
        onPointerDown={startResize}
        title="Drag to resize"
        role="separator"
        aria-label="Resize chatbot"
      >
        <GripVertical size={15} />
      </div>

      <h3>
        <Bot size={16} />
        AI Repository Assistant
        <span className="chat-size-hint">Drag to resize</span>
      </h3>

      <div className="messages">
        {messages.map((message, index) => (
          <div className={`msg ${message.role}`} key={index}>
            <span>
              {message.role === "assistant" ? (
                <Bot size={15} />
              ) : (
                <UserRound size={15} />
              )}
            </span>

            <div className="msg-content">
              <div>{message.text}</div>

              {message.sources?.length > 0 && (
                <div className="sources">
                  {message.sources.map((source) => (
                    <span key={source}>{source}</span>
                  ))}
                </div>
              )}
            </div>
          </div>
        ))}

        {busy && (
          <div className="msg assistant">
            <span>
              <Bot size={15} />
            </span>
            <div className="typing">
              Analyzing repository<span>.</span><span>.</span><span>.</span>
            </div>
          </div>
        )}

        <div ref={messagesEnd} />
      </div>

      <form onSubmit={submit}>
        <input
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="Ask about the code..."
          disabled={busy}
        />

        <button
          type="submit"
          disabled={busy || !question.trim()}
          aria-label="Send question"
        >
          <Send size={17} />
        </button>
      </form>
    </section>
  );
}
