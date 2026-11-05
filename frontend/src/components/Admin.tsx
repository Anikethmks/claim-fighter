import { useEffect, useState } from "react";
import { api, type Metrics } from "../api";

const LABELS: Record<string, string> = {
  users: "Users", cases: "Cases started", analysed: "Analyses finished", waiting_for_user: "Waiting for user",
  failed: "Failed", cases_with_letter: "Cases with a letter", letters: "Letters drafted",
  chat_questions: "Chat questions", outcomes_reported: "Outcomes reported", won_or_partial: "Won or partly won",
  amount_recovered_inr: "Amount recovered (₹)", ai_cost_usd: "AI cost ($)", cost_per_case_usd: "AI cost per case ($)",
};

/** Adoption and cost dashboard for the owner. */
export default function Admin() {
  const [m, setM] = useState<Metrics | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.metrics().then(setM).catch((e) => setError((e as Error).message));
  }, []);

  if (error) return <section className="card"><div className="alert alert-error">{error}</div></section>;
  if (!m) return <section className="card"><div className="spinner" /></section>;
  const t = m.totals;
  const pct = (a: number, b: number) => (b ? `${Math.round((a / b) * 100)}%` : "—");

  return (
    <>
      <section className="card">
        <h1>Adoption</h1>
        <div className="stats">
          {Object.entries(LABELS).map(([k, label]) => (
            <div key={k} className="stat"><div className="stat-value">{t[k]?.toLocaleString("en-IN") ?? 0}</div><div className="stat-label">{label}</div></div>
          ))}
        </div>
        <h3>Funnel</h3>
        <p className="muted">
          Started → analysed {pct(t.analysed, t.cases)} · analysed → letter {pct(t.cases_with_letter, t.analysed)} ·
          letter → outcome reported {pct(t.outcomes_reported, t.cases_with_letter)} · reported → won {pct(t.won_or_partial, t.outcomes_reported)}
        </p>
        <p className="fine">Daily AI budget: ${m.daily_budget_usd}. New AI work stops for the day once it's reached.</p>
      </section>
      <section className="card">
        <h2>Last 30 days</h2>
        <table className="table">
          <thead><tr><th>Day</th><th>New users</th><th>Cases</th><th>AI cost ($)</th></tr></thead>
          <tbody>
            {m.daily.map((d) => (
              <tr key={d.day}><td>{d.day}</td><td>{d.new_users}</td><td>{d.cases}</td><td>{d.cost_usd.toFixed(3)}</td></tr>
            ))}
          </tbody>
        </table>
      </section>
    </>
  );
}
