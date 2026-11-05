import { useEffect, useRef, useState } from "react";
import { api, type ChatMessage } from "../api";
import { SourceCard } from "./Sources";

const TOOL_LABELS: Record<string, string> = {
  get_case_summary: "read your case",
  search_rules: "searched the rules",
  get_deadlines: "checked deadlines",
  record_new_fact: "noted a new fact",
  draft_letter: "drafted a letter",
};

const SUGGESTIONS = [
  "When is my last date to go to the Ombudsman?",
  "The hospital had no cheaper room available. Does that help?",
  "Write the complaint letter in simpler English.",
];

function Message({ m }: { m: ChatMessage }) {
  const [showRefs, setShowRefs] = useState(false);
  return (
    <div className={`msg msg-${m.role}`}>
      <div className="msg-body">{m.content}</div>
      {m.role === "assistant" && (m.tools_used.length > 0 || m.references.length > 0) && (
        <div className="msg-meta">
          {m.tools_used.length > 0 && <span>Agent {m.tools_used.map((t) => TOOL_LABELS[t] ?? t).join(" · ")}</span>}
          {m.references.length > 0 && (
            <button type="button" className="btn-link" onClick={() => setShowRefs(!showRefs)}>
              {showRefs ? "Hide" : "Show"} {m.references.length} source{m.references.length > 1 ? "s" : ""}
            </button>
          )}
        </div>
      )}
      {showRefs && m.references.map((r, i) => <SourceCard key={r.id} entry={r} index={i + 1} />)}
    </div>
  );
}

/** Case Assistant: a tool-using agent (OpenAI Agents SDK) that answers follow-up questions. */
export default function Chat({ caseId, initial, onReanalysing }: {
  caseId: string; initial: ChatMessage[]; onReanalysing: () => void;
}) {
  const [messages, setMessages] = useState(initial);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const end = useRef<HTMLDivElement>(null);

  useEffect(() => end.current?.scrollIntoView({ block: "nearest" }), [messages.length, busy]);

  async function send(message: string) {
    if (!message.trim() || busy) return;
    setBusy(true);
    setError(null);
    setMessages((m) => [...m, { role: "user", content: message, created_at: "", references: [], tools_used: [] }]);
    setText("");
    try {
      const r = await api.chat(caseId, message);
      setMessages((m) => [...m, r.message]);
      if (r.reanalysing) onReanalysing();
    } catch (e) {
      setError((e as Error).message);
      setMessages((m) => m.slice(0, -1));
      setText(message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card chat">
      <h2>Ask about your case</h2>
      <p className="muted">The assistant reads your case, searches the rules and checks your deadlines before answering.</p>
      <div className="msgs">
        {messages.length === 0 && (
          <div className="suggestions">
            {SUGGESTIONS.map((s) => (
              <button key={s} type="button" className="chip" onClick={() => send(s)} disabled={busy}>{s}</button>
            ))}
          </div>
        )}
        {messages.map((m, i) => <Message key={i} m={m} />)}
        {busy && <div className="msg msg-assistant msg-typing">Thinking…</div>}
        <div ref={end} />
      </div>
      {error && <div className="alert alert-error" role="alert">{error}</div>}
      <form className="chat-input" onSubmit={(e) => { e.preventDefault(); send(text); }}>
        <input value={text} onChange={(e) => setText(e.target.value)} maxLength={1000}
          placeholder="e.g. Does it matter that I've had this policy since 2018?" disabled={busy} />
        <button className="btn btn-primary" disabled={busy || !text.trim()}>Send</button>
      </form>
    </section>
  );
}
