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

export default function Timeline({ caseId, initial, initialMilestones }: {
  caseId: string; initial: TimelineStep[]; initialMilestones: Record<string, string>;
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
