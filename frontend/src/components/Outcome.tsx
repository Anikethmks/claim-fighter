import { useState } from "react";
import { api } from "../api";

const OPTIONS = [
  { value: "pending", label: "Still waiting" },
  { value: "won", label: "Got paid in full" },
  { value: "partial", label: "Got paid partly" },
  { value: "lost", label: "Lost" },
];

/** Outcome reporting: this is what lets the product learn which arguments work. */
export default function Outcome({ caseId, initial }: {
  caseId: string; initial: { outcome: string | null; amount_recovered: number | null; notes: string | null };
}) {
  const [outcome, setOutcome] = useState(initial.outcome ?? "");
  const [amount, setAmount] = useState(initial.amount_recovered?.toString() ?? "");
  const [notes, setNotes] = useState(initial.notes ?? "");
  const [state, setState] = useState<"idle" | "saving" | "saved" | "error">("idle");

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setState("saving");
    try {
      await api.setOutcome(caseId, outcome, amount ? Number(amount) : null, notes);
      setState("saved");
    } catch {
      setState("error");
    }
  }

  return (
    <section className="card">
      <h2>How did it go?</h2>
      <p className="muted">Tell us the result, even weeks later. It helps the next person in the same situation.</p>
      <form onSubmit={save} className="outcome-form">
        <div className="seg" role="radiogroup">
          {OPTIONS.map((o) => (
            <label key={o.value} className={`seg-opt ${outcome === o.value ? "seg-on" : ""}`}>
              <input type="radio" name="outcome" value={o.value} checked={outcome === o.value} onChange={() => setOutcome(o.value)} />
              {o.label}
            </label>
          ))}
        </div>
        {(outcome === "won" || outcome === "partial") && (
          <label className="field"><span>Amount recovered (₹)</span>
            <input type="number" min={0} inputMode="numeric" value={amount} onChange={(e) => setAmount(e.target.value)} />
          </label>
        )}
        <label className="field"><span>What worked or didn't? <span className="opt">optional</span></span>
          <input value={notes} onChange={(e) => setNotes(e.target.value)} maxLength={2000} />
        </label>
        <button className="btn btn-secondary" disabled={!outcome || state === "saving"}>
          {state === "saving" ? "Saving…" : state === "saved" ? "Saved, thank you" : "Save"}
        </button>
        {state === "error" && <span className="error-text">Couldn't save. Try again.</span>}
      </form>
    </section>
  );
}
