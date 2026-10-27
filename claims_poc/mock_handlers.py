"""Offline stand-ins for the agents so the pipeline can be tested without an API key.
They test the plumbing (schemas, orchestration, guardrails), NOT model quality."""
from __future__ import annotations

import re
from difflib import SequenceMatcher


def classifier(p):
    out = []
    for d in p["documents"]:
        head = d["text"].strip().splitlines()[0].upper()
        t = ("CLAIM_FORM" if "CLAIM FORM" in head else "HOSPITAL_BILL" if "BILL" in head else
             "DISCHARGE_SUMMARY" if "DISCHARGE" in head else "PRESCRIPTION" if "PRESCRIPTION" in head else
             "ID_PROOF" if "ID PROOF" in head else "OTHER")
        out.append({"filename": d["filename"], "doc_type": t, "confidence": 0.95 if t != "OTHER" else 0.4})
    return {"docs": out}


_KEYS = {"patient": "patient_name", "policy no": "policy_number", "hospital": "hospital_name",
         "bill no": "bill_number", "admission date": "admission_date", "discharge date": "discharge_date",
         "bill date": "bill_date", "submission date": "submission_date", "diagnosis": "diagnosis",
         "doctor": "doctor_name", "doctor reg no": "doctor_reg_no"}


def extractor(p):
    r = {"filename": p["filename"], "doc_type": p["doc_type"], "line_items": []}
    for line in p["text"].splitlines():
        line = line.strip()
        if line.startswith("- ") and "|" in line:
            desc, cat, qty, price, amt = [x.strip() for x in line[2:].split("|")]
            r["line_items"].append({"description": desc, "category": cat, "quantity": float(qty),
                                    "unit_price": float(price), "amount": float(amt)})
        elif ":" in line:
            k, v = [x.strip() for x in line.split(":", 1)]
            if k.lower() in _KEYS:
                r[_KEYS[k.lower()]] = v
            elif k.lower() in ("total", "claim amount"):
                r["total_amount"] = float(re.sub(r"[^\d.]", "", v))
    return r


def consistency(p):
    docs = p["documents"]
    ref = next((d for d in docs if d["doc_type"] == "CLAIM_FORM"), docs[0])
    findings = []
    for d in docs:
        if d["patient_name"] and ref["patient_name"]:
            ratio = SequenceMatcher(None, d["patient_name"].lower(), ref["patient_name"].lower()).ratio()
            if ratio < 0.8:
                findings.append({"agent": "consistency", "severity": "BLOCKER", "code": "NAME_MISMATCH",
                                 "message": f"Patient name '{d['patient_name']}' in {d['filename']} does not match '{ref['patient_name']}'"})
            elif ratio < 1:
                findings.append({"agent": "consistency", "severity": "WARN", "code": "NAME_VARIANT",
                                 "message": f"Name variant '{d['patient_name']}' vs '{ref['patient_name']}'"})
    return {"agent": "consistency", "summary": f"{len(findings)} issue(s) found", "findings": findings}


def coverage(p):
    findings = []
    diag = " ".join(d["diagnosis"] or "" for d in p["documents"]).lower()
    for term in p["policy"]["exclusions"]:
        if term.lower() in diag:
            findings.append({"agent": "coverage", "severity": "BLOCKER", "code": "EXCLUDED_TREATMENT",
                             "message": f"Diagnosis matches policy exclusion: {term}"})
    for term, days in p["policy"]["specific_waiting_days"].items():
        if term in diag:
            findings.append({"agent": "coverage", "severity": "BLOCKER", "code": "SPECIFIC_WAITING_PERIOD",
                             "message": f"'{term}' has a {days}-day waiting period; check admission date against inception {p['policy']['inception_date']}",
                             "evidence": p["admission_date"]})
    return {"agent": "coverage", "summary": f"{len(findings)} coverage issue(s)", "findings": findings}


def fraud(p):
    n = len(p["rule_findings"])
    return {"agent": "fraud", "summary": f"Reviewed {n} rule flag(s) and claim history", "findings": []}


def decision(p):
    f = p["findings"]
    codes = {x["code"] for x in f}
    blockers = [x for x in f if x["severity"] == "BLOCKER"]
    warns = [x for x in f if x["severity"] == "WARN"]
    if "MISSING_DOC" in codes:
        d = "QUERY_MORE_INFO"
    elif blockers:
        d = "REJECT"
    elif warns:
        d = "ESCALATE_TO_HUMAN"
    elif p["payable"]["approved"] < (p["payable"]["claimed"] or 0):
        d = "PARTIAL_APPROVE"
    else:
        d = "APPROVE"
    reasons = [x["message"] for x in blockers + warns] or ["All checks passed"]
    return {"decision": d, "reasons": reasons, "confidence": 0.9,
            "missing_documents": [x["message"].split(": ")[1] for x in f if x["code"] == "MISSING_DOC"]}


HANDLERS = {"classifier": classifier, "extractor": extractor, "consistency": consistency,
            "coverage": coverage, "fraud": fraud, "decision": decision}
