import { useState } from "react";
import { api } from "../api";

/** Questions the case workflow paused on. Required ones block analysis; optional ones refine it. */
export default function Questions({ caseId, questions, kind, onSubmitted }: {
  caseId: string; questions: string[]; kind: "required" | "optional"; onSubmitted: () => void;
}) {
  const [answers, setAnswers] = useState<string[]>(questions.map(() => ""));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const anyAnswered = answers.some((a) => a.trim());

  async function send(skip: boolean) {
    setBusy(true);
    setError(null);
    try {
      const payload = skip ? [] : questions.map((q, i) => ({ question: q, answer: answers[i] })).filter((a) => a.answer.trim());
      await api.answer(caseId, payload);
      onSubmitted();
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  return (
    <section className={`card questions ${kind === "required" ? "questions-required" : ""}`}>
      <h2>{kind === "required" ? "We need a little more information" : "Answer these to sharpen your verdict"}</h2>
      <p className="muted">
        {kind === "required"
          ? "We couldn't find this in your documents, and the analysis depends on it."
          : "Your documents don't say. Answers can change the result; skip any you don't know."}
      </p>
      {questions.map((q, i) => (
        <label key={q} className="field">
          <span>{q}</span>
          <textarea rows={2} value={answers[i]} maxLength={1000}
            onChange={(e) => setAnswers((prev) => prev.map((a, j) => (j === i ? e.target.value : a)))} />
        </label>
      ))}
      {error && <div className="alert alert-error" role="alert">{error}</div>}
      <div className="row">
        <button className="btn btn-primary" disabled={busy || !anyAnswered} onClick={() => send(false)}>
          {busy ? "Sending…" : "Re-check my case"}
        </button>
        {kind === "optional" && (
          <button className="btn btn-secondary" disabled={busy} onClick={() => send(true)}>Skip</button>
        )}
      </div>
    </section>
  );
}
