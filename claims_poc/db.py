"""Azure SQL (or SQLite locally) via SQLAlchemy. Source of truth for claims, findings and reviews."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote_plus

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, Boolean, create_engine, delete, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class PolicyRow(Base):
    __tablename__ = "policies"
    policy_number: Mapped[str] = mapped_column(String(50), primary_key=True)
    policy_json: Mapped[str] = mapped_column(Text)


class ClaimRow(Base):
    __tablename__ = "claims"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    policy_number: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(30), default="RECEIVED")  # RECEIVED, PROCESSING, AWAITING_REVIEW, COMPLETED, FAILED
    ai_decision: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    claimed_amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    approved_amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    human_review_required: Mapped[bool] = mapped_column(Boolean, default=True)
    final_decision: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    error: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DocRow(Base):
    __tablename__ = "claim_documents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    claim_id: Mapped[str] = mapped_column(String(40), ForeignKey("claims.id"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    blob_name: Mapped[str] = mapped_column(String(400))
    doc_type: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)


class FindingRow(Base):
    __tablename__ = "findings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    claim_id: Mapped[str] = mapped_column(String(40), ForeignKey("claims.id"), index=True)
    agent: Mapped[str] = mapped_column(String(30))
    severity: Mapped[str] = mapped_column(String(10))
    code: Mapped[str] = mapped_column(String(60))
    message: Mapped[str] = mapped_column(Text)
    evidence: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class BillRow(Base):
    """Every bill we have processed. Used to catch the same bill being claimed twice."""
    __tablename__ = "bills"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hospital_name: Mapped[str] = mapped_column(String(200))
    bill_number: Mapped[str] = mapped_column(String(100))
    claim_id: Mapped[str] = mapped_column(String(40))
    amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    __table_args__ = (Index("ix_bills_bill_number", "bill_number"),)


class ReviewRow(Base):
    __tablename__ = "reviews"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    claim_id: Mapped[str] = mapped_column(String(40), ForeignKey("claims.id"), index=True)
    reviewer: Mapped[str] = mapped_column(String(100))
    final_decision: Mapped[str] = mapped_column(String(30))
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


def make_engine(url: str | None = None):
    cs = os.getenv("AZURE_SQL_CONN_STR")  # ODBC string, e.g. "Driver={ODBC Driver 18 for SQL Server};Server=tcp:...;..."
    url = url or (("mssql+pyodbc:///?odbc_connect=" + quote_plus(cs)) if cs else os.getenv("SQL_URL", "sqlite:///./local.db"))
    kwargs = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {"pool_pre_ping": True}
    return create_engine(url, **kwargs)


class Repo:
    def __init__(self, engine=None):
        self.engine = engine or make_engine()
        self.Session = sessionmaker(self.engine, expire_on_commit=False)

    def init(self):
        Base.metadata.create_all(self.engine)

    # ---- demo seed data ----
    def seed_policy(self, policy: dict):
        with self.Session() as s:
            if not s.get(PolicyRow, policy["policy_number"]):
                s.add(PolicyRow(policy_number=policy["policy_number"], policy_json=json.dumps(policy)))
                s.commit()

    def seed_history(self, history: list[dict]):
        with self.Session() as s:
            for h in history:
                exists = s.scalar(select(BillRow).where(BillRow.bill_number == h["bill_number"], BillRow.claim_id == h["claim_id"]))
                if not exists:
                    s.add(BillRow(hospital_name=h["hospital"], bill_number=h["bill_number"], claim_id=h["claim_id"], amount=h["amount"]))
            s.commit()

    # ---- policies ----
    def get_policy(self, policy_number: str) -> Optional[dict]:
        with self.Session() as s:
            row = s.get(PolicyRow, policy_number)
            return json.loads(row.policy_json) if row else None

    # ---- claims ----
    def create_claim(self, claim_id: str, policy_number: str, files: list[tuple[str, str]]):
        with self.Session() as s:
            s.add(ClaimRow(id=claim_id, policy_number=policy_number))
            s.flush()
            for filename, blob_name in files:
                s.add(DocRow(claim_id=claim_id, filename=filename, blob_name=blob_name))
            s.commit()

    def set_status(self, claim_id: str, status: str, error: str | None = None):
        with self.Session() as s:
            c = s.get(ClaimRow, claim_id)
            c.status, c.error, c.updated_at = status, error, utcnow()
            s.commit()

    def save_result(self, claim_id: str, result: dict):
        d = result["decision"]
        with self.Session() as s:
            c = s.get(ClaimRow, claim_id)
            c.ai_decision, c.confidence = d["decision"], d["confidence"]
            c.claimed_amount, c.approved_amount = d["claimed_amount"], d["approved_amount"]
            c.human_review_required = d["human_review_required"]
            c.status = "AWAITING_REVIEW" if d["human_review_required"] else "COMPLETED"
            c.final_decision = None if d["human_review_required"] else d["decision"]
            c.error, c.updated_at = None, utcnow()
            s.execute(delete(FindingRow).where(FindingRow.claim_id == claim_id))
            for f in result["findings"]:
                s.add(FindingRow(claim_id=claim_id, agent=f["agent"], severity=f["severity"], code=f["code"],
                                 message=f["message"], evidence=f.get("evidence")))
            types = {x["filename"]: x["doc_type"] for x in result["classification"]}
            for row in s.scalars(select(DocRow).where(DocRow.claim_id == claim_id)):
                row.doc_type = types.get(row.filename)
            s.commit()

    def get_claim(self, claim_id: str) -> Optional[dict]:
        with self.Session() as s:
            c = s.get(ClaimRow, claim_id)
            if not c:
                return None
            find = s.scalars(select(FindingRow).where(FindingRow.claim_id == claim_id).order_by(FindingRow.id))
            docs = s.scalars(select(DocRow).where(DocRow.claim_id == claim_id))
            revs = s.scalars(select(ReviewRow).where(ReviewRow.claim_id == claim_id).order_by(ReviewRow.id))
            return {
                "claim_id": c.id, "policy_number": c.policy_number, "status": c.status,
                "ai_decision": c.ai_decision, "confidence": c.confidence, "claimed_amount": c.claimed_amount,
                "approved_amount": c.approved_amount, "human_review_required": c.human_review_required,
                "final_decision": c.final_decision, "error": c.error,
                "created_at": c.created_at.isoformat(), "updated_at": c.updated_at.isoformat(),
                "documents": [{"filename": d.filename, "doc_type": d.doc_type} for d in docs],
                "findings": [{"agent": f.agent, "severity": f.severity, "code": f.code, "message": f.message,
                              "evidence": f.evidence} for f in find],
                "reviews": [{"reviewer": r.reviewer, "final_decision": r.final_decision, "comment": r.comment,
                             "created_at": r.created_at.isoformat()} for r in revs],
            }

    def list_claims(self, limit: int = 50) -> list[dict]:
        with self.Session() as s:
            rows = s.scalars(select(ClaimRow).order_by(ClaimRow.created_at.desc()).limit(limit))
            return [{"claim_id": c.id, "policy_number": c.policy_number, "status": c.status,
                     "ai_decision": c.ai_decision, "final_decision": c.final_decision,
                     "claimed_amount": c.claimed_amount, "approved_amount": c.approved_amount,
                     "human_review_required": c.human_review_required, "created_at": c.created_at.isoformat()}
                    for c in rows]

    def claim_doc_names(self, claim_id: str) -> list[tuple[str, str]]:
        with self.Session() as s:
            return [(d.filename, d.blob_name) for d in s.scalars(select(DocRow).where(DocRow.claim_id == claim_id))]

    # ---- duplicate detection ----
    def history_for(self, bill_number: str, exclude_claim_id: str) -> list[dict]:
        with self.Session() as s:
            rows = s.scalars(select(BillRow).where(BillRow.bill_number == bill_number, BillRow.claim_id != exclude_claim_id))
            return [{"claim_id": r.claim_id, "bill_number": r.bill_number, "hospital": r.hospital_name, "amount": r.amount}
                    for r in rows]

    def register_bill(self, hospital: str, bill_number: str, claim_id: str, amount: float | None):
        with self.Session() as s:
            if not s.scalar(select(BillRow).where(BillRow.bill_number == bill_number, BillRow.claim_id == claim_id)):
                s.add(BillRow(hospital_name=hospital or "", bill_number=bill_number, claim_id=claim_id, amount=amount))
                s.commit()

    # ---- human review ----
    def add_review(self, claim_id: str, reviewer: str, final_decision: str, comment: str):
        with self.Session() as s:
            s.add(ReviewRow(claim_id=claim_id, reviewer=reviewer, final_decision=final_decision, comment=comment))
            c = s.get(ClaimRow, claim_id)
            c.final_decision, c.status, c.updated_at = final_decision, "COMPLETED", utcnow()
            s.commit()
