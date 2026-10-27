"""The six agents. Each is a specialist: its own prompt, its own input, its own typed output."""
from __future__ import annotations

from .llm import LLM
from .schemas import AgentReport, ClassificationResult, Decision, ExtractedDoc

COMMON = ("You are a careful health-insurance claims assistant. Use ONLY the evidence given. "
          "Never invent facts. If something is unclear, say so instead of guessing. ")


def classify(llm: LLM, documents: list[dict]) -> ClassificationResult:
    system = COMMON + (
        "Agent: DOCUMENT CLASSIFIER. For each document decide its type: CLAIM_FORM, HOSPITAL_BILL, "
        "DISCHARGE_SUMMARY, PRESCRIPTION, ID_PROOF or OTHER. Give a confidence from 0 to 1.")
    return llm.run("classifier", system, {"documents": documents}, ClassificationResult)


def extract(llm: LLM, filename: str, doc_type: str, text: str) -> ExtractedDoc:
    system = COMMON + (
        "Agent: EXTRACTOR. Pull structured fields out of ONE document. Dates must be YYYY-MM-DD. "
        "Amounts are plain numbers in INR with no symbols. Leave a field null if it is not in the text. "
        "For bills, list every line item with a category: ROOM, PROFESSIONAL, MEDICINE, DIAGNOSTIC, "
        "CONSUMABLE or OTHER. Copy numbers exactly as written; do not fix or recalculate them.")
    return llm.run("extractor", system, {"filename": filename, "doc_type": doc_type, "text": text}, ExtractedDoc)


def consistency(llm: LLM, extracted: list[ExtractedDoc]) -> AgentReport:
    system = COMMON + (
        "Agent: CONSISTENCY CHECKER. Compare the documents of one claim. Check: (1) the patient name is the "
        "same person across documents (allow initials and spelling variants, flag different people), "
        "(2) hospital name and doctor details agree, (3) the diagnosis, the treatment on the bill and the "
        "medicines are medically coherent. Report each problem as a finding with agent='consistency', a short "
        "UPPER_SNAKE code, a clear message and evidence. BLOCKER = clearly different person or contradiction; "
        "WARN = possible issue; INFO = note.")
    return llm.run("consistency", system, {"documents": [d.model_dump() for d in extracted]}, AgentReport)


def coverage(llm: LLM, extracted: list[ExtractedDoc], policy: dict) -> AgentReport:
    system = COMMON + (
        "Agent: COVERAGE CHECKER. Decide whether the diagnosis and treatment fall under the policy exclusions "
        "or specific waiting periods. Map the diagnosis to the policy terms even when wording differs (for "
        "example 'inguinal hernia repair' matches 'hernia'). If a waiting period applies, compare admission "
        "date with the policy inception date. Do NOT calculate payable amounts; the system does that. "
        "Use agent='coverage'. BLOCKER only when the policy text clearly excludes the claim.")
    adm = next((d.admission_date for d in extracted if d.admission_date), None)
    payload = {"documents": [d.model_dump() for d in extracted], "policy": policy, "admission_date": adm}
    return llm.run("coverage", system, payload, AgentReport)


def fraud(llm: LLM, extracted: list[ExtractedDoc], rule_findings: list, history: list[dict]) -> AgentReport:
    system = COMMON + (
        "Agent: FRAUD AND ANOMALY ANALYST. Look for signs of fraud or error: duplicate or reused bills, "
        "inflated or unusual charges for the stated diagnosis, bill totals that do not add up, documents "
        "that contradict each other, missing registration numbers. Use the rule findings and past claims "
        "as extra evidence. Be careful: unusual is not the same as fraud. Say 'possible' unless the "
        "evidence is clear. Use agent='fraud'.")
    payload = {"documents": [d.model_dump() for d in extracted],
               "rule_findings": [f.model_dump() for f in rule_findings], "past_claims": history}
    return llm.run("fraud", system, payload, AgentReport)


def decide(llm: LLM, findings: list, payable: dict) -> Decision:
    system = COMMON + (
        "Agent: DECISION SUPERVISOR. Read all findings and recommend ONE outcome. "
        "APPROVE: complete documents, no WARN or BLOCKER. "
        "PARTIAL_APPROVE: valid claim, but the payable amount is lower than claimed only because of policy "
        "deductions (non-payables, room rent cap, co-pay), with no integrity warnings. "
        "QUERY_MORE_INFO: documents missing or unclear and the customer can fix it. "
        "REJECT: a clear exclusion, waiting period or duplicate, backed by a BLOCKER. "
        "ESCALATE_TO_HUMAN: fraud signals, conflicting evidence, or you are not sure. "
        "Give short reasons that cite the finding codes. You do not compute amounts; the system does. "
        "A human adjudicator makes the final call, so be honest about confidence.")
    payload = {"findings": [f.model_dump() for f in findings], "payable": payable}
    return llm.run("decision", system, payload, Decision)
