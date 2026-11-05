// Typed client for the ClaimFighter API. Shapes mirror backend/app/schemas.py.

export type Strength = "strong" | "moderate" | "weak" | "unclear";
export type Stage = "insurer_grievance" | "bima_bharosa" | "ombudsman" | "consumer_commission";

export interface KBEntry {
  id: string;
  kind: "regulation" | "process" | "ombudsman_award" | "ombudsman_stats" | "court_judgment";
  title: string;
  body: string;
  source_name: string;
  source_url: string | null;
  verified: boolean;
}

export interface Deduction {
  item: string;
  amount: number | null;
  reason_given: string;
}

export interface CaseFacts {
  insurer_name: string | null;
  policy_name: string | null;
  policy_number: string | null;
  policy_start_date: string | null;
  continuous_coverage_since: string | null;
  sum_insured: number | null;
  room_rent_limit: string | null;
  hospital_name: string | null;
  admission_date: string | null;
  discharge_date: string | null;
  diagnosis: string | null;
  treatment: string | null;
  claim_type: string;
  claim_amount: number | null;
  amount_approved: number | null;
  decision: string;
  decision_date: string | null;
  rejection_reasons: string[];
  clauses_cited_by_insurer: string[];
  deductions: Deduction[];
  documents_missing_or_unreadable: string[];
  summary: string;
}

export interface Issue {
  title: string;
  insurer_position: string;
  assessment: string;
  strength: Strength;
  amount_at_stake: number | null;
  citation_ids: string[];
  evidence_to_gather: string[];
}

export interface Analysis {
  overall_strength: Strength;
  headline: string;
  issues: Issue[];
  amount_recoverable_estimate: number | null;
  questions_for_user: string[];
  honest_caveats: string[];
  recommended_next_stage: Stage | "none";
}

export interface TimelineStep {
  key: string;
  title: string;
  status: "done" | "current" | "upcoming" | "missed";
  done_on: string | null;
  earliest: string | null;
  deadline: string | null;
  explanation: string;
  kb_ids: string[];
}

export interface Draft {
  id: string;
  stage: Stage;
  body: string;
  created_at?: string;
  references: KBEntry[];
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  created_at: string;
  references: KBEntry[];
  tools_used: string[];
}

export type CaseStatus = "processing" | "extracted" | "checking" | "rechecking" | "needs_input" | "analyzed" | "failed";
export const BUSY_STATUSES: CaseStatus[] = ["processing", "extracted", "checking", "rechecking"];

export interface CaseView {
  id: string;
  created_at: string;
  status: CaseStatus;
  questions: string[];
  question_kind: "required" | "optional" | null;
  self_check: { consistent: boolean; problems: string[] } | null;
  chat: ChatMessage[];
  chat_enabled: boolean;
  error: string | null;
  facts: CaseFacts | null;
  computed: Record<string, unknown> | null;
  analysis: Analysis | null;
  citations_removed: string[];
  knowledge: KBEntry[];
  timeline: TimelineStep[];
  milestones: Record<string, string>;
  drafts: Draft[];
  documents: { role: string; filename: string }[];
  outcome: { outcome: string | null; amount_recovered: number | null; notes: string | null };
}

export interface DraftRequest {
  stage: Stage;
  complainant_name?: string;
  complainant_address?: string;
  complainant_phone?: string;
  extra_instructions?: string;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, init);
  } catch {
    throw new Error("Can't reach the server. Check your connection and try again.");
  }
  if (res.status === 204) return undefined as T;
  const body = await res.json().catch(() => null);
  if (res.status === 401) throw new AuthError("Please sign in.");
  if (!res.ok) {
    const detail = body?.detail;
    throw new Error(typeof detail === "string" ? detail : `Request failed (${res.status}).`);
  }
  return body as T;
}

const json = (method: string, data: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(data),
});

export interface Me { email: string; admin: boolean }
export interface CaseListItem { id: string; created_at: string; status: CaseStatus; insurer: string | null; strength: Strength | null }
export interface Metrics {
  totals: Record<string, number>;
  daily: { day: string; cases: number; cost_usd: number; new_users: number }[];
  daily_budget_usd: number;
}

export class AuthError extends Error {}

export const api = {
  me: () => request<Me>("/api/auth/me"),
  requestCode: (email: string) => request<{ ok: boolean }>("/api/auth/request", json("POST", { email })),
  verifyCode: (email: string, code: string) => request<Me>("/api/auth/verify", json("POST", { email, code })),
  logout: () => request<{ ok: boolean }>("/api/auth/logout", { method: "POST" }),
  listCases: () => request<CaseListItem[]>("/api/cases"),
  metrics: () => request<Metrics>("/api/admin/metrics"),
  createCase: (form: FormData) => request<{ id: string }>("/api/cases", { method: "POST", body: form }),
  getCase: (id: string) => request<CaseView>(`/api/cases/${id}`),
  reanalyze: (id: string) => request<{ id: string }>(`/api/cases/${id}/reanalyze`, { method: "POST" }),
  answer: (id: string, answers: { question: string; answer: string }[]) =>
    request<{ status: CaseStatus }>(`/api/cases/${id}/answers`, json("POST", { answers })),
  insurerReply: (id: string, replied_on: string, reply_text: string) =>
    request<{ draft: Draft; timeline: TimelineStep[]; milestones: Record<string, string> }>(
      `/api/cases/${id}/insurer-reply`, json("POST", { replied_on, reply_text })),
  chat: (id: string, message: string) =>
    request<{ message: ChatMessage; reanalysing: boolean }>(`/api/cases/${id}/chat`, json("POST", { message })),
  createDraft: (id: string, req: DraftRequest) => request<Draft>(`/api/cases/${id}/drafts`, json("POST", req)),
  setMilestone: (id: string, kind: string, happened_on: string) =>
    request<{ timeline: TimelineStep[]; milestones: Record<string, string> }>(
      `/api/cases/${id}/milestones`, json("PUT", { kind, happened_on })),
  clearMilestone: (id: string, kind: string) =>
    request<{ timeline: TimelineStep[]; milestones: Record<string, string> }>(
      `/api/cases/${id}/milestones/${kind}`, { method: "DELETE" }),
  setOutcome: (id: string, outcome: string, amount_recovered: number | null, notes: string) =>
    request<{ ok: boolean }>(`/api/cases/${id}/outcome`, json("POST", { outcome, amount_recovered, notes })),
  deleteCase: (id: string) => request<void>(`/api/cases/${id}`, { method: "DELETE" }),
};

export const STAGE_LABELS: Record<Stage, string> = {
  insurer_grievance: "Complaint to insurer",
  bima_bharosa: "IRDAI Bima Bharosa portal",
  ombudsman: "Insurance Ombudsman",
  consumer_commission: "Consumer commission",
};

export const rupees = (n: number | null | undefined) =>
  n == null ? "—" : "₹" + Math.round(n).toLocaleString("en-IN");

export const prettyDate = (iso: string | null | undefined) => {
  if (!iso) return "—";
  const d = new Date(iso + (iso.length === 10 ? "T00:00:00" : ""));
  return isNaN(d.getTime()) ? iso : d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
};
