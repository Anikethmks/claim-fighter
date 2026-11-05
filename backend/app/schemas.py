"""Pydantic shapes for LLM structured outputs and API payloads.

The LLM-facing models avoid numeric/length constraints because structured
outputs only support a subset of JSON Schema; validation of business rules
happens in code after parsing.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel


# ---------- Step 1: extraction ----------

class Deduction(BaseModel):
    item: str
    amount: Optional[float]
    reason_given: str


class CaseFacts(BaseModel):
    insurer_name: Optional[str]
    policy_name: Optional[str]
    policy_number: Optional[str]
    policy_type: Literal["individual", "family_floater", "group_employer", "government_scheme", "unknown"]
    policy_start_date: Optional[str]          # ISO yyyy-mm-dd when known
    continuous_coverage_since: Optional[str]  # earliest date of continuous cover incl. portability
    sum_insured: Optional[float]
    room_rent_limit: Optional[str]
    patient_age: Optional[int]
    hospital_name: Optional[str]
    admission_date: Optional[str]
    discharge_date: Optional[str]
    diagnosis: Optional[str]
    treatment: Optional[str]
    claim_type: Literal["cashless", "reimbursement", "unknown"]
    claim_amount: Optional[float]
    amount_approved: Optional[float]
    decision: Literal["fully_rejected", "partially_settled", "cashless_denied", "pending", "unknown"]
    decision_date: Optional[str]
    specific_reason_given: bool               # a real ground (clause, exclusion, medical reason), not "not admissible"
    rejection_reasons: list[str]
    clauses_cited_by_insurer: list[str]
    deductions: list[Deduction]
    documents_missing_or_unreadable: list[str]
    summary: str


# ---------- Step 2: analysis ----------

class Issue(BaseModel):
    title: str
    insurer_position: str
    assessment: str
    strength: Literal["strong", "moderate", "weak", "unclear"]
    amount_at_stake: Optional[float]
    citation_ids: list[str]
    evidence_to_gather: list[str]


class Analysis(BaseModel):
    overall_strength: Literal["strong", "moderate", "weak", "unclear"]
    headline: str
    issues: list[Issue]
    amount_recoverable_estimate: Optional[float]
    questions_for_user: list[str]
    honest_caveats: list[str]
    recommended_next_stage: Literal["insurer_grievance", "bima_bharosa", "ombudsman", "consumer_commission", "none"]


class SelfCheck(BaseModel):
    consistent: bool
    problems: list[str]


# ---------- API payloads ----------

Stage = Literal["insurer_grievance", "bima_bharosa", "ombudsman", "consumer_commission"]


class DraftRequest(BaseModel):
    stage: Stage
    complainant_name: Optional[str] = None
    complainant_address: Optional[str] = None
    complainant_phone: Optional[str] = None
    extra_instructions: Optional[str] = None


class MilestoneIn(BaseModel):
    kind: str
    happened_on: str


class Answer(BaseModel):
    question: str
    answer: str


class AnswersIn(BaseModel):
    answers: list[Answer]       # empty list = skip the questions


class ChatIn(BaseModel):
    message: str


class OutcomeIn(BaseModel):
    outcome: Literal["won", "partial", "lost", "pending"]
    amount_recovered: Optional[float] = None
    notes: Optional[str] = None


class EmailIn(BaseModel):
    email: str


class VerifyIn(BaseModel):
    email: str
    code: str
