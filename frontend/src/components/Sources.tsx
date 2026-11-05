import { useState } from "react";
import type { KBEntry } from "../api";

const KIND_LABEL: Record<KBEntry["kind"], string> = {
  regulation: "Rule",
  process: "Process",
  ombudsman_award: "Ombudsman decision",
  ombudsman_stats: "Ombudsman record",
  court_judgment: "Court judgment",
};

export function SourceCard({ entry, index }: { entry: KBEntry; index?: number }) {
  return (
    <div className="source">
      <div className="source-head">
        {index != null && <span className="ref-num">[{index}]</span>}
        <span className="kind">{KIND_LABEL[entry.kind]}</span>
        {!entry.verified && <span className="badge badge-warn" title="Plain-language summary. Check the official source before relying on it.">Check source</span>}
      </div>
      <div className="source-title">{entry.title}</div>
      <p className="source-body">{entry.body}</p>
      <div className="source-meta">
        {entry.source_name}
        {entry.source_url && (
          <> · <a href={entry.source_url} target="_blank" rel="noreferrer">Official source ↗</a></>
        )}
      </div>
    </div>
  );
}

/** Inline chips for an issue's citations; clicking one expands the source. */
export function Citations({ ids, knowledge }: { ids: string[]; knowledge: Map<string, KBEntry> }) {
  const [open, setOpen] = useState<string | null>(null);
  const entries = ids.map((id) => knowledge.get(id)).filter((e): e is KBEntry => !!e);
  if (!entries.length) return null;
  return (
    <div className="citations">
      <div className="chips">
        <span className="chips-label">Based on:</span>
        {entries.map((e) => (
          <button
            key={e.id}
            type="button"
            className={`chip ${open === e.id ? "chip-on" : ""}`}
            aria-expanded={open === e.id}
            onClick={() => setOpen(open === e.id ? null : e.id)}
          >
            {e.title}
          </button>
        ))}
      </div>
      {open && knowledge.get(open) && <SourceCard entry={knowledge.get(open)!} />}
    </div>
  );
}
