"""Supervisor: runs the agents in order, runs independent ones in parallel, enforces guardrails."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import agents
from .llm import LLM
from .rules import claimed_amount, compute_payable, run_rules
from .schemas import DocType, Finding


def read_documents(claim_dir: Path) -> list[dict]:
    docs = []
    for p in sorted(claim_dir.iterdir()):
        if p.suffix.lower() == ".txt":
            text = p.read_text(encoding="utf-8")
        elif p.suffix.lower() == ".pdf":
            from pypdf import PdfReader
            text = "\n".join(page.extract_text() or "" for page in PdfReader(p).pages)
        else:
            continue  # scanned images need OCR / vision: see README
        docs.append({"filename": p.name, "text": text})
    return docs


def apply_guardrails(decision, all_findings, payable: dict, missing: list[str], claimed: float | None):
    """Code overrules the model where it must. Shared by the plain pipeline and the LangGraph version."""
    decision.claimed_amount = claimed
    has_blocker = any(f.severity == "BLOCKER" for f in all_findings)
    has_warn = any(f.severity == "WARN" for f in all_findings)
    if decision.decision in ("APPROVE", "PARTIAL_APPROVE") and (has_blocker or has_warn):
        decision.reasons.insert(0, "Guardrail: model suggested approval but open findings exist")
        decision.decision = "ESCALATE_TO_HUMAN"
    fraud_codes = {"DUPLICATE_BILL", "BILL_TOTAL_MISMATCH", "NAME_MISMATCH"}
    if decision.decision != "ESCALATE_TO_HUMAN" and any(f.code in fraud_codes for f in all_findings):
        decision.reasons.insert(0, "Guardrail: possible fraud signal, so a human reviews it instead of asking the customer to fix it")
        decision.decision = "ESCALATE_TO_HUMAN"
    if decision.confidence < 0.7 and decision.decision != "ESCALATE_TO_HUMAN":
        decision.reasons.insert(0, "Guardrail: low confidence")
        decision.decision = "ESCALATE_TO_HUMAN"
    decision.missing_documents = missing or decision.missing_documents
    decision.approved_amount = payable["approved"] if decision.decision in ("APPROVE", "PARTIAL_APPROVE") else 0.0
    decision.human_review_required = decision.decision != "APPROVE"
    return decision


def process_claim_dir(claim_dir: Path, llm: LLM, policy: dict, history: list[dict]) -> dict:
    """Folder + JSON-history version, used by the CLI and offline tests."""
    def history_fn(bill_number: str) -> list[dict]:
        return [h for h in history if h["bill_number"].lower() == (bill_number or "").lower()]
    return process_claim(claim_dir.name, read_documents(claim_dir), llm, policy, history_fn)


def process_claim(claim_id: str, documents: list[dict], llm: LLM, policy: dict, history_fn) -> dict:
    """documents: [{"filename", "text"}]; text is None for files we cannot read.
    history_fn(bill_number) -> earlier claims that used the same bill number."""
    unreadable = [d["filename"] for d in documents if not d.get("text")]
    documents = [d for d in documents if d.get("text")]

    # 1. Classify, then extract each document in parallel
    classification = agents.classify(llm, documents)
    type_by_file = {c.filename: c.doc_type for c in classification.docs}
    with ThreadPoolExecutor(max_workers=5) as pool:
        extracted = list(pool.map(
            lambda d: agents.extract(llm, d["filename"], type_by_file[d["filename"]].value, d["text"]), documents))
    for e in extracted:  # trust the classifier's type over whatever the extractor echoed
        e.doc_type = type_by_file[e.filename]

    # 2. Deterministic rules and payable amount (no LLM)
    bill = next((e for e in extracted if e.doc_type == DocType.HOSPITAL_BILL), None)
    history = history_fn(bill.bill_number) if bill and bill.bill_number else []
    rule_findings, missing = run_rules(extracted, policy, history)
    for name in unreadable:
        rule_findings.append(Finding(agent="rules", severity="WARN", code="UNREADABLE_DOC",
                                     message=f"{name} could not be read (scanned or unsupported). OCR is needed."))
    payable = compute_payable(extracted, policy)

    # 3. Three independent specialist agents in parallel
    with ThreadPoolExecutor(max_workers=3) as pool:
        f_cons = pool.submit(agents.consistency, llm, extracted)
        f_cov = pool.submit(agents.coverage, llm, extracted, policy)
        f_fraud = pool.submit(agents.fraud, llm, extracted, rule_findings, history)
        reports = [f_cons.result(), f_cov.result(), f_fraud.result()]

    all_findings: list[Finding] = rule_findings + [f for r in reports for f in r.findings]

    # 4. Supervisor recommends a decision
    decision = agents.decide(llm, all_findings, payable)

    # 5. Guardrails: code overrules the model where it must
    apply_guardrails(decision, all_findings, payable, missing, claimed_amount(extracted))

    return {
        "claim_id": claim_id,
        "decision": decision.model_dump(),
        "payable_breakdown": payable,
        "findings": [f.model_dump() for f in all_findings],
        "agent_summaries": {r.agent: r.summary for r in reports},
        "classification": [c.model_dump(mode="json") for c in classification.docs],
        "extracted": [e.model_dump(mode="json") for e in extracted],
        "llm_calls": llm.calls,
    }


def save(result: dict, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{result['claim_id']}.json"
    path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    return path
