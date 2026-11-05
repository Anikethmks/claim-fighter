import { useState } from "react";
import { api, prettyDate, type TimelineStep } from "../api";

const MILESTONE_INPUTS: { kind: string; label: string }[] = [
  { kind: "decision_received", label: "Insurer's rejection / settlement letter dated" },
  { kind: "grievance_sent", label: "I sent my complaint to the insurer on" },
  { kind: "insurer_replied", label: "Insurer replied to my complaint on" },
  { kind: "ombudsman_filed", label: "I filed with the Ombudsman on" },
  { kind: "ombudsman_award", label: "Ombudsman award received on" },
];

const STATUS_LABEL: Record<TimelineStep["status"], string> = {
  done: "Done",
  current: "Do this now",
  upcoming: "Later",
  missed: "Deadline passed",
};

function InsurerReply({ caseId, onDone }: {
  caseId: string; onDone: (r: { timeline: TimelineStep[]; milestones: Record<string, string> }) => void;
}) {
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await api.insurerReply(caseId, date, text);
      onDone(r);
      setDone(true);
      setText("");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="reply-box" onSubmit={submit}>
      <h3>Got a reply from the insurer?</h3>
      <p className="fine">Paste it here. We'll record the date (it starts your Ombudsman clock) and draft your Ombudsman
        complaint answering each point.</p>
      <label className="field-inline"><span>Reply dated</span>
        <input type="date" required value={date} onChange={(e) => setDate(e.target.value)} />
      </label>
      <label className="field"><span>The insurer's reply</span>
        <textarea rows={4} required minLength={20} maxLength={6000} value={text} onChange={(e) => setText(e.target.value)}
          placeholder="Copy the text of their email or letter" />
      </label>
      {error && <div className="alert alert-error" role="alert">{error}</div>}
      {done && <div className="alert alert-info">Done. Your Ombudsman complaint is in "Get your complaint drafted" below.</div>}
      <button className="btn btn-primary" disabled={busy || text.trim().length < 20}>
        {busy ? "Drafting your Ombudsman complaint…" : "Draft my Ombudsman complaint"}
      </button>
    </form>
  );
}

export default function Timeline({ caseId, initial, initialMilestones, onDrafted }: {
  caseId: string; initial: TimelineStep[]; initialMilestones: Record<string, string>; onDrafted: () => void;
}) {
  const [timeline, setTimeline] = useState(initial);
  const [milestones, setMilestones] = useState(initialMilestones);
  const [error, setError] = useState<string | null>(null);

  async function update(kind: string, value: string) {
    setError(null);
    try {
      const r = value ? await api.setMilestone(caseId, kind, value) : await api.clearMilestone(caseId, kind);
      setTimeline(r.timeline);
      setMilestones(r.milestones);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <section className="card">
      <h2>Your steps and deadlines</h2>
      <ol className="timeline">
        {timeline.map((s) => (
          <li key={s.key} className={`tl tl-${s.status}`}>
            <div className="tl-head">
              <span className={`tl-status st-${s.status}`}>{STATUS_LABEL[s.status]}</span>
              <span className="tl-title">{s.title}</span>
            </div>
            <p className="tl-expl">{s.explanation}</p>
            <div className="tl-dates">
              {s.done_on && <span>Done on <strong>{prettyDate(s.done_on)}</strong></span>}
              {s.earliest && !s.done_on && <span>Earliest: <strong>{prettyDate(s.earliest)}</strong></span>}
              {s.deadline && !s.done_on && <span>Last date: <strong>{prettyDate(s.deadline)}</strong></span>}
            </div>
          </li>
        ))}
      </ol>

      {milestones.grievance_sent && !milestones.ombudsman_filed && (
        <InsurerReply caseId={caseId} onDone={(r) => { setTimeline(r.timeline); setMilestones(r.milestones); onDrafted(); }} />
      )}

      <details className="milestones">
        <summary>Update what has happened so far</summary>
        <p className="fine">Dates recalculate instantly. They follow the published rules; confirm anything critical with the office concerned.</p>
        <div className="milestone-grid">
          {MILESTONE_INPUTS.map((m) => (
            <label key={m.kind} className="field-inline">
              <span>{m.label}</span>
              <input type="date" value={milestones[m.kind] ?? ""} onChange={(e) => update(m.kind, e.target.value)} />
            </label>
          ))}
        </div>
        {error && <div className="alert alert-error">{error}</div>}
      </details>
    </section>
  );
}
