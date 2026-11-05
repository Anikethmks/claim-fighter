import { useEffect, useMemo, useState } from "react";
import { api, BUSY_STATUSES, prettyDate, rupees, type CaseStatus, type CaseView, type Issue, type KBEntry, type Strength } from "../api";
import { Citations } from "./Sources";
import Timeline from "./Timeline";
import Drafts from "./Drafts";
import Outcome from "./Outcome";
import Questions from "./Questions";
import Chat from "./Chat";

const STRENGTH: Record<Strength, { label: string; verdict: string }> = {
  strong: { label: "Strong", verdict: "You have a strong case to contest this." },
  moderate: { label: "Moderate", verdict: "You have a reasonable case, worth contesting." },
  weak: { label: "Weak", verdict: "The insurer's decision looks largely correct." },
  unclear: { label: "Unclear", verdict: "We need more information to judge this." },
};

// Mirrors the LangGraph workflow: each status means the step before it has finished.
const PROGRESS = ["Reading your documents", "Checking the rules and writing your assessment",
  "Double-checking it against your policy"];
const STEP_FOR: Partial<Record<CaseStatus, number>> = { processing: 0, extracted: 1, checking: 2, rechecking: 1 };

function Processing({ status, hasAnalysis }: { status: CaseStatus; hasAnalysis: boolean }) {
  const step = status === "processing" && hasAnalysis ? 1 : STEP_FOR[status] ?? 0;
  return (
    <section className="card processing" aria-live="polite">
      <div className="spinner" aria-hidden />
      <h2>{hasAnalysis && status === "processing" ? "Re-checking your case" : "Analysing your claim"}</h2>
      <ol className="progress">
        {PROGRESS.map((p, i) => (
          <li key={p} className={i < step ? "p-done" : i === step ? "p-now" : ""}>{p}</li>
        ))}
      </ol>
      {status === "rechecking" && (
        <p className="fine">The double-check found something to fix, so the assessment is being corrected.</p>
      )}
      <p className="fine">This usually takes under a minute. You can leave this page; your case is saved on this device.</p>
    </section>
  );
}

function IssueCard({ issue, knowledge }: { issue: Issue; knowledge: Map<string, KBEntry> }) {
  return (
    <article className={`issue s-${issue.strength}`}>
      <div className="issue-head">
        <h3>{issue.title}</h3>
        <span className={`pill pill-${issue.strength}`}>{STRENGTH[issue.strength].label}</span>
      </div>
      {issue.amount_at_stake != null && <div className="issue-amount">{rupees(issue.amount_at_stake)} at stake</div>}
      <div className="issue-cols">
        <div><div className="col-label">Insurer says</div><p>{issue.insurer_position}</p></div>
        <div><div className="col-label">What we found</div><p>{issue.assessment}</p></div>
      </div>
      {issue.evidence_to_gather.length > 0 && (
        <div className="evidence">
          <div className="col-label">Gather this to strengthen your case</div>
          <ul>{issue.evidence_to_gather.map((e) => <li key={e}>{e}</li>)}</ul>
        </div>
      )}
      <Citations ids={issue.citation_ids} knowledge={knowledge} />
    </article>
  );
}

export default function CasePage({ id }: { id: string }) {
  const [data, setData] = useState<CaseView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [pollKey, setPollKey] = useState(0);

  useEffect(() => {
    let alive = true;
    let timer: number | undefined;
    const load = async () => {
      try {
        const c = await api.getCase(id);
        if (!alive) return;
        setData(c);
        setError(null);
        if (BUSY_STATUSES.includes(c.status)) timer = window.setTimeout(load, 2500);
      } catch (e) {
        if (alive) setError((e as Error).message);
      }
    };
    load();
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
  }, [id, pollKey]);

  const knowledge = useMemo(() => new Map((data?.knowledge ?? []).map((k) => [k.id, k])), [data?.knowledge]);

  async function retry() {
    try {
      await api.reanalyze(id);
      setPollKey((k) => k + 1);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function remove() {
    if (!window.confirm("Delete this case and all uploaded documents permanently?")) return;
    setDeleting(true);
    try {
      await api.deleteCase(id);
      window.location.hash = "#/";
    } catch (e) {
      setError((e as Error).message);
      setDeleting(false);
    }
  }

  if (error && !data) {
    return (
      <section className="card">
        <h2>Couldn't open this case</h2>
        <div className="alert alert-error">{error}</div>
        <a className="btn btn-secondary" href="#/">Start a new case</a>
      </section>
    );
  }
  if (!data) return <section className="card"><div className="spinner" /></section>;
  const refresh = () => setPollKey((k) => k + 1);
  if (BUSY_STATUSES.includes(data.status)) return <Processing status={data.status} hasAnalysis={!!data.analysis} />;
  if (data.status === "needs_input") {
    return <Questions caseId={id} questions={data.questions} kind="required" onSubmitted={refresh} />;
  }

  if (data.status === "failed") {
    return (
      <section className="card">
        <h2>We couldn't finish the analysis</h2>
        <div className="alert alert-error">{data.error}</div>
        <div className="row">
          <button className="btn btn-primary" onClick={retry}>Try again</button>
          <a className="btn btn-secondary" href="#/">Upload different documents</a>
        </div>
      </section>
    );
  }

  const { facts, analysis } = data;
  if (!facts || !analysis) return null;
  const s = STRENGTH[analysis.overall_strength];

  return (
    <div className="case">
      <section className={`card verdict v-${analysis.overall_strength}`}>
        <div className="verdict-top">
          <span className={`pill pill-${analysis.overall_strength}`}>{s.label} case</span>
          {analysis.amount_recoverable_estimate != null && (
            <span className="recoverable">Possibly recoverable: <strong>{rupees(analysis.amount_recoverable_estimate)}</strong></span>
          )}
        </div>
        <h1>{s.verdict}</h1>
        <p className="lead">{analysis.headline}</p>
        {data.self_check && (
          data.self_check.consistent ? (
            <p className="check check-ok">✓ Double-checked against your policy documents</p>
          ) : (
            <details className="check check-warn">
              <summary>⚠ Our double-check flagged points to verify yourself</summary>
              <ul>{data.self_check.problems.map((p) => <li key={p}>{p}</li>)}</ul>
            </details>
          )
        )}
      </section>

      {data.question_kind === "optional" && data.questions.length > 0 && (
        <Questions key={data.questions.join("|")} caseId={id} questions={data.questions} kind="optional" onSubmitted={refresh} />
      )}

      <section className="card facts">
        <h2>What happened</h2>
        <p>{facts.summary}</p>
        <dl className="facts-grid">
          <div><dt>Insurer</dt><dd>{facts.insurer_name ?? "—"}</dd></div>
          <div><dt>Policy</dt><dd>{[facts.policy_name, facts.policy_number].filter(Boolean).join(" · ") || "—"}</dd></div>
          <div><dt>Claimed</dt><dd>{rupees(facts.claim_amount)}</dd></div>
          <div><dt>Paid</dt><dd>{rupees(facts.amount_approved)}</dd></div>
          <div><dt>Hospital stay</dt><dd>{prettyDate(facts.admission_date)} – {prettyDate(facts.discharge_date)}</dd></div>
          <div><dt>Covered since</dt><dd>{prettyDate(facts.continuous_coverage_since ?? facts.policy_start_date)}</dd></div>
        </dl>
        {facts.rejection_reasons.length > 0 && (
          <>
            <h3>Reasons the insurer gave</h3>
            <ul>{facts.rejection_reasons.map((r) => <li key={r}>{r}</li>)}</ul>
          </>
        )}
        {facts.documents_missing_or_unreadable.length > 0 && (
          <div className="alert alert-info">
            <strong>Missing or unreadable:</strong> {facts.documents_missing_or_unreadable.join("; ")}. Adding these may change the assessment.
          </div>
        )}
      </section>

      <section className="issues">
        <h2 className="section-title">Point by point</h2>
        {analysis.issues.map((issue) => <IssueCard key={issue.title} issue={issue} knowledge={knowledge} />)}
      </section>

      {analysis.honest_caveats.length > 0 && (
        <section className="card">
          <h3>Limits of this analysis</h3>
          <ul>{analysis.honest_caveats.map((c) => <li key={c}>{c}</li>)}</ul>
        </section>
      )}

      {data.chat_enabled && <Chat caseId={id} initial={data.chat} onReanalysing={refresh} />}

      <Timeline caseId={id} initial={data.timeline} initialMilestones={data.milestones} onDrafted={refresh} />
      {analysis.overall_strength === "weak" && (
        <div className="alert alert-info">
          <strong>Our honest view:</strong> the insurer's decision looks correct under your policy, so a complaint is
          unlikely to succeed. You can still draft one, for example if you have facts the documents don't show.
        </div>
      )}
      <Drafts key={data.drafts.length} caseId={id} initial={data.drafts} recommended={analysis.recommended_next_stage} />
      <Outcome caseId={id} initial={data.outcome} />

      <section className="danger-zone">
        <button className="btn-link danger" onClick={remove} disabled={deleting}>
          {deleting ? "Deleting…" : "Delete this case and my documents"}
        </button>
      </section>
    </div>
  );
}
