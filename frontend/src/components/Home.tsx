import { useEffect, useRef, useState } from "react";
import { api, prettyDate, type CaseListItem, type Me } from "../api";
import Login from "./Login";

type Role = "rejection" | "policy" | "bill";

const SLOTS: { role: Role; label: string; hint: string; required?: boolean }[] = [
  { role: "rejection", label: "Rejection or settlement letter", hint: "The letter or email from the insurer/TPA explaining the cut or rejection.", required: true },
  { role: "policy", label: "Policy document", hint: "Policy wording and schedule. The wording matters most: that's where the clauses are." },
  { role: "bill", label: "Hospital bill or discharge summary", hint: "Itemised final bill if you have it; otherwise the discharge summary." },
];

const ACCEPT = "application/pdf,image/jpeg,image/png,image/webp";

function FileSlot({ label, hint, required, file, onFile }: {
  label: string; hint: string; required?: boolean; file: File | null; onFile: (f: File | null) => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  return (
    <div
      className={`slot ${file ? "slot-filled" : ""} ${over ? "slot-over" : ""}`}
      onDragOver={(e) => { e.preventDefault(); setOver(true); }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); onFile(e.dataTransfer.files[0] ?? null); }}
    >
      <div className="slot-text">
        <div className="slot-label">{label} {required ? <span className="req">required</span> : <span className="opt">recommended</span>}</div>
        <div className="slot-hint">{file ? file.name : hint}</div>
      </div>
      <div className="slot-actions">
        {file && <button type="button" className="btn-link" onClick={() => onFile(null)}>Remove</button>}
        <button type="button" className="btn btn-secondary" onClick={() => input.current?.click()}>
          {file ? "Change" : "Choose file"}
        </button>
      </div>
      <input ref={input} type="file" accept={ACCEPT} hidden onChange={(e) => onFile(e.target.files?.[0] ?? null)} />
    </div>
  );
}

export default function Home({ me, onSignedIn }: { me: Me | null; onSignedIn: (me: Me) => void }) {
  const [files, setFiles] = useState<Record<Role, File | null>>({ rejection: null, policy: null, bill: null });
  const [notes, setNotes] = useState("");
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [previous, setPrevious] = useState<CaseListItem[]>([]);

  useEffect(() => {
    if (me) api.listCases().then(setPrevious).catch(() => {});
  }, [me]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!files.rejection) {
      setError("Please add the rejection or settlement letter. It's the one document we can't work without.");
      return;
    }
    if (!consent) {
      setError("Please tick the consent box so we can process your documents.");
      return;
    }
    setBusy(true);
    setError(null);
    const form = new FormData();
    (Object.keys(files) as Role[]).forEach((role) => files[role] && form.append(role, files[role]!));
    if (notes.trim()) form.append("notes", notes.trim());
    form.append("consent", "true");
    try {
      const { id } = await api.createCase(form);
      window.location.hash = `#/case/${id}`;
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <>
      <section className="hero">
        <h1>Insurance rejected or cut your health claim?</h1>
        <p className="lead">
          Upload the letter, your policy and the bill. In about two minutes you'll know whether the insurer's
          reason holds up, which rules apply, your deadlines, and a complaint letter ready to send.
        </p>
        <ul className="hero-points">
          <li><strong>Reads your actual policy</strong>, not generic advice</li>
          <li><strong>Only cites real sources</strong>: every rule links to where it comes from</li>
          <li><strong>Honest</strong>: if the insurer is right, we'll tell you</li>
        </ul>
      </section>

      {!me && <Login onSignedIn={onSignedIn} title="Sign in to start your case" />}

      {me && <form className="card upload" onSubmit={submit}>
        <h2>Start your case</h2>
        {SLOTS.map((s) => (
          <FileSlot key={s.role} {...s} file={files[s.role]} onFile={(f) => setFiles((p) => ({ ...p, [s.role]: f }))} />
        ))}
        <label className="field">
          <span>Anything we should know? <span className="opt">optional</span></span>
          <textarea
            rows={3}
            value={notes}
            maxLength={4000}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="e.g. I've had this policy since 2018 with another insurer and ported in 2023. The hospital only had a twin-sharing room free."
          />
        </label>
        <p className="fine">PDF, JPG, PNG or WEBP, up to 20 MB each. Phone photos are fine if the text is readable.</p>
        <label className="consent">
          <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
          <span>
            I agree that ClaimFighter may process these documents, which include health information, to analyse my
            claim. They're sent to our AI provider for analysis and deleted after 30 days. I'm the patient, or I have
            their permission. <a href="#/privacy" target="_blank" rel="noreferrer">Privacy details</a>
          </span>
        </label>
        {error && <div className="alert alert-error" role="alert">{error}</div>}
        <button className="btn btn-primary btn-lg" disabled={busy}>
          {busy ? "Uploading…" : "Analyse my claim"}
        </button>
      </form>}

      {previous.length > 0 && (
        <section className="card">
          <h3>Your cases</h3>
          <ul className="plain-list">
            {previous.map((c) => (
              <li key={c.id}>
                <a href={`#/case/${c.id}`}>{c.insurer ?? "Case"} · {prettyDate(c.created_at.slice(0, 10))}</a>
                {c.strength && <span className={`pill pill-${c.strength}`} style={{ marginLeft: 8 }}>{c.strength}</span>}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="how">
        <h2>How a claim fight usually goes</h2>
        <ol className="steps">
          <li><strong>Complain to the insurer</strong> in writing. Required before the Ombudsman.</li>
          <li><strong>Insurance Ombudsman</strong>: free, no lawyer needed, after the insurer replies or a month passes.</li>
          <li><strong>Consumer commission</strong> if needed, within two years.</li>
        </ol>
        <p className="fine">ClaimFighter drafts each step and tracks the dates for you.</p>
      </section>
    </>
  );
}
