import { useState } from "react";
import { api, STAGE_LABELS, prettyDate, type Draft, type Stage } from "../api";
import { SourceCard } from "./Sources";

const STAGE_HELP: Record<Stage, string> = {
  insurer_grievance: "Send to the insurer's grievance officer by email or their grievance portal. Keep the acknowledgement.",
  bima_bharosa: "Paste into IRDAI's Bima Bharosa portal (bimabharosa.irdai.gov.in) to log it with the regulator.",
  ombudsman: "File online on the Council for Insurance Ombudsmen site (cioins.co.in) after the insurer replies or a month passes.",
  consumer_commission: "A starting draft for the District Commission, filed online via e-Jagriti. Have it reviewed before filing.",
};

function download(name: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: "text/plain;charset=utf-8" }));
  const a = Object.assign(document.createElement("a"), { href: url, download: name });
  a.click();
  URL.revokeObjectURL(url);
}

function DraftView({ draft }: { draft: Draft }) {
  const [copied, setCopied] = useState(false);
  const withRefs = draft.references.length
    ? `${draft.body}\n\nReferences\n${draft.references.map((r, i) => `[${i + 1}] ${r.title}. ${r.source_name}${r.source_url ? ` (${r.source_url})` : ""}`).join("\n")}`
    : draft.body;

  async function copy() {
    try {
      await navigator.clipboard.writeText(withRefs);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      /* clipboard blocked; user can still download */
    }
  }

  return (
    <div className="draft">
      <div className="draft-head">
        <div>
          <strong>{STAGE_LABELS[draft.stage]}</strong>
          {draft.created_at && <span className="muted"> · {prettyDate(draft.created_at.slice(0, 10))}</span>}
        </div>
        <div className="draft-actions">
          <button type="button" className="btn btn-secondary" onClick={copy}>{copied ? "Copied" : "Copy"}</button>
          <button type="button" className="btn btn-secondary" onClick={() => download(`claim-${draft.stage}.txt`, withRefs)}>Download</button>
        </div>
      </div>
      <pre className="draft-body">{draft.body}</pre>
      {draft.references.length > 0 && (
        <div className="refs">
          <h4>References used in this letter</h4>
          {draft.references.map((r, i) => <SourceCard key={r.id} entry={r} index={i + 1} />)}
        </div>
      )}
    </div>
  );
}

export default function Drafts({ caseId, initial, recommended }: {
  caseId: string; initial: Draft[]; recommended: Stage | "none";
}) {
  const [drafts, setDrafts] = useState(initial);
  const [stage, setStage] = useState<Stage>(recommended === "none" ? "insurer_grievance" : recommended);
  const [name, setName] = useState("");
  const [address, setAddress] = useState("");
  const [phone, setPhone] = useState("");
  const [extra, setExtra] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function generate(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const d = await api.createDraft(caseId, {
        stage,
        complainant_name: name || undefined,
        complainant_address: address || undefined,
        complainant_phone: phone || undefined,
        extra_instructions: extra || undefined,
      });
      setDrafts([d, ...drafts]);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card">
      <h2>Get your complaint drafted</h2>
      <form className="draft-form" onSubmit={generate}>
        <fieldset className="stages">
          <legend>Which step are you on?</legend>
          {(Object.keys(STAGE_LABELS) as Stage[]).map((s) => (
            <label key={s} className={`stage ${stage === s ? "stage-on" : ""}`}>
              <input type="radio" name="stage" value={s} checked={stage === s} onChange={() => setStage(s)} />
              <span className="stage-name">{STAGE_LABELS[s]}{s === recommended && <span className="badge">recommended</span>}</span>
              <span className="stage-help">{STAGE_HELP[s]}</span>
            </label>
          ))}
        </fieldset>
        <div className="grid-3">
          <label className="field"><span>Your name</span><input value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" /></label>
          <label className="field"><span>Phone</span><input value={phone} onChange={(e) => setPhone(e.target.value)} autoComplete="tel" /></label>
          <label className="field"><span>Address</span><input value={address} onChange={(e) => setAddress(e.target.value)} autoComplete="street-address" /></label>
        </div>
        <label className="field">
          <span>Anything to add or change? <span className="opt">optional</span></span>
          <input value={extra} onChange={(e) => setExtra(e.target.value)} placeholder="e.g. Mention that I called the TPA twice; write it in simpler English" />
        </label>
        <p className="fine">Details you leave blank appear as [placeholders] to fill in yourself. What you enter is saved only inside the draft, and deleted when you delete the case.</p>
        {error && <div className="alert alert-error" role="alert">{error}</div>}
        <button className="btn btn-primary" disabled={busy}>{busy ? "Writing your letter… (up to a minute)" : "Draft the letter"}</button>
      </form>
      {drafts.map((d) => <DraftView key={d.id} draft={d} />)}
    </section>
  );
}
