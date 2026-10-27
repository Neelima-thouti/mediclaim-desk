"""Typed contracts between agents. Every LLM answer is validated against these."""
from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


class DocType(str, Enum):
    CLAIM_FORM = "CLAIM_FORM"
    HOSPITAL_BILL = "HOSPITAL_BILL"
    DISCHARGE_SUMMARY = "DISCHARGE_SUMMARY"
    PRESCRIPTION = "PRESCRIPTION"
    ID_PROOF = "ID_PROOF"
    OTHER = "OTHER"


class ClassifiedDoc(BaseModel):
    filename: str
    doc_type: DocType
    confidence: float = Field(ge=0, le=1)


class ClassificationResult(BaseModel):
    docs: list[ClassifiedDoc]


class LineItem(BaseModel):
    description: str
    category: Literal["ROOM", "PROFESSIONAL", "MEDICINE", "DIAGNOSTIC", "CONSUMABLE", "OTHER"]
    quantity: float = 1
    unit_price: Optional[float] = None
    amount: float


class ExtractedDoc(BaseModel):
    filename: str
    doc_type: DocType
    patient_name: Optional[str] = None
    policy_number: Optional[str] = None
    hospital_name: Optional[str] = None
    bill_number: Optional[str] = None
    admission_date: Optional[str] = None   # YYYY-MM-DD
    discharge_date: Optional[str] = None   # YYYY-MM-DD
    bill_date: Optional[str] = None        # YYYY-MM-DD
    submission_date: Optional[str] = None  # YYYY-MM-DD
    diagnosis: Optional[str] = None
    doctor_name: Optional[str] = None
    doctor_reg_no: Optional[str] = None
    total_amount: Optional[float] = None
    line_items: list[LineItem] = []


Severity = Literal["INFO", "WARN", "BLOCKER"]


class Finding(BaseModel):
    agent: str
    severity: Severity
    code: str
    message: str
    evidence: Optional[str] = None


class AgentReport(BaseModel):
    agent: str
    summary: str
    findings: list[Finding] = []


class Decision(BaseModel):
    decision: Literal["APPROVE", "PARTIAL_APPROVE", "QUERY_MORE_INFO", "REJECT", "ESCALATE_TO_HUMAN"]
    reasons: list[str]
    missing_documents: list[str] = []
    confidence: float = Field(ge=0, le=1)
    # Filled by code, never trusted from the model:
    approved_amount: Optional[float] = None
    claimed_amount: Optional[float] = None
    human_review_required: bool = True
