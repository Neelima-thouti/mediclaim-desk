"""Evaluation harness: run many labelled claims and measure the system.
    python -m claims_poc.evaluate --make-cases          # creates data/eval/* from the clean sample claim
    python -m claims_poc.evaluate --mock                # runs them with the fake agents (tests the harness)
    python -m claims_poc.evaluate --provider azure      # runs them with the real model
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from .llm import LLM
from .orchestrator import process_claim_dir

APPROVING = ("APPROVE", "PARTIAL_APPROVE")

# Each case changes the clean claim in ONE way and records what a correct system must do.
CASES = [
    {"name": "c01_clean", "edits": {}, "delete": [],
     "expected": {"acceptable": ["APPROVE", "PARTIAL_APPROVE"], "must_flag": [], "must_not_approve": False, "expected_amount": 81450}},
    {"name": "c02_missing_id_proof", "edits": {}, "delete": ["id_proof.txt"],
     "expected": {"acceptable": ["QUERY_MORE_INFO"], "must_flag": ["MISSING_DOC"], "must_not_approve": True}},
    {"name": "c03_wrong_bill_total", "edits": {"hospital_bill.txt": [("Total: 93000", "Total: 99000")]}, "delete": [],
     "expected": {"acceptable": ["ESCALATE_TO_HUMAN"], "must_flag": ["BILL_TOTAL_MISMATCH"], "must_not_approve": True}},
    {"name": "c04_patient_name_mismatch", "edits": {"discharge_summary.txt": [("Patient: Ravi Kumar Sharma", "Patient: Rohit Sharma")]}, "delete": [],
     "expected": {"acceptable": ["ESCALATE_TO_HUMAN"], "must_flag": ["NAME_MISMATCH"], "must_not_approve": True}},
    {"name": "c05_duplicate_bill", "edits": {"hospital_bill.txt": [("Bill No: B-55021", "Bill No: B-77821")]}, "delete": [],
     "expected": {"acceptable": ["ESCALATE_TO_HUMAN"], "must_flag": ["DUPLICATE_BILL"], "must_not_approve": True}},
    {"name": "c06_hernia_waiting_period",
     "edits": {"hospital_bill.txt": [("Acute appendicitis - laparoscopic appendectomy", "Right inguinal hernia - open mesh repair")],
               "discharge_summary.txt": [("Acute appendicitis - laparoscopic appendectomy", "Right inguinal hernia - open mesh repair")],
               "prescription.txt": [("Acute appendicitis", "Right inguinal hernia")]}, "delete": [],
     "expected": {"acceptable": ["REJECT", "ESCALATE_TO_HUMAN"], "must_flag": ["SPECIFIC_WAITING_PERIOD"], "must_not_approve": True}},
    {"name": "c07_late_filing", "edits": {"claim_form.txt": [("Submission Date: 2026-08-20", "Submission Date: 2026-10-10")]}, "delete": [],
     "expected": {"acceptable": ["ESCALATE_TO_HUMAN"], "must_flag": ["LATE_SUBMISSION"], "must_not_approve": True}},
    {"name": "c08_room_rent_over_cap",
     "edits": {"hospital_bill.txt": [("| ROOM | 3 | 4000 | 12000", "| ROOM | 3 | 7500 | 22500"), ("Total: 93000", "Total: 103500")],
               "claim_form.txt": [("Claim Amount: 93000", "Claim Amount: 103500")]}, "delete": [],
     "expected": {"acceptable": ["PARTIAL_APPROVE"], "must_flag": [], "must_not_approve": False, "expected_amount": 84150}},
    {"name": "c09_wrong_policy_number", "edits": {"hospital_bill.txt": [("Policy No: POL-123456", "Policy No: POL-999999")]}, "delete": [],
     "expected": {"acceptable": ["REJECT", "ESCALATE_TO_HUMAN"], "must_flag": ["POLICY_NUMBER_MISMATCH"], "must_not_approve": True}},
]


def make_cases(base_dir: Path, out_dir: Path) -> None:
    for case in CASES:
        dest = out_dir / case["name"]
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(base_dir, dest)
        for fname in case["delete"]:
            (dest / fname).unlink()
        for fname, pairs in case["edits"].items():
            text = (dest / fname).read_text(encoding="utf-8")
            for old, new in pairs:
                assert old in text, f"{case['name']}: '{old}' not found in {fname}"
                text = text.replace(old, new)
            (dest / fname).write_text(text, encoding="utf-8")
        (dest / "expected.json").write_text(json.dumps(case["expected"], indent=2), encoding="utf-8")


def run_case(case_dir: Path, llm_factory, policy: dict, history: list[dict]) -> dict:
    expected = json.loads((case_dir / "expected.json").read_text())
    # expected.json is not a claim document, so move it out of the way by only reading .txt/.pdf (read_documents does that)
    llm = llm_factory()
    result = process_claim_dir(case_dir, llm, policy, history)
    d = result["decision"]
    codes = {f["code"] for f in result["findings"]}
    flags_found = [c for c in expected["must_flag"] if c in codes]
    amount_ok = None
    if "expected_amount" in expected:
        amount_ok = d["decision"] in APPROVING and abs((d["approved_amount"] or 0) - expected["expected_amount"]) < 1
    return {
        "case": case_dir.name,
        "decision": d["decision"],
        "decision_ok": d["decision"] in expected["acceptable"],
        "false_approval": bool(expected["must_not_approve"] and d["decision"] in APPROVING),
        "flags_expected": len(expected["must_flag"]),
        "flags_found": len(flags_found),
        "amount_ok": amount_ok,
        "seconds": round(sum(c["seconds"] for c in llm.calls), 2),
        "prompt_tokens": sum(c.get("prompt_tokens", 0) for c in llm.calls),
        "completion_tokens": sum(c.get("completion_tokens", 0) for c in llm.calls),
    }


def summarise(rows: list[dict]) -> dict:
    n = len(rows)
    flags_exp = sum(r["flags_expected"] for r in rows)
    amounts = [r for r in rows if r["amount_ok"] is not None]
    return {
        "cases": n,
        "decision_accuracy": round(sum(r["decision_ok"] for r in rows) / n, 3),
        "false_approvals": sum(r["false_approval"] for r in rows),
        "flag_recall": round(sum(r["flags_found"] for r in rows) / flags_exp, 3) if flags_exp else None,
        "amount_accuracy": round(sum(r["amount_ok"] for r in amounts) / len(amounts), 3) if amounts else None,
        "avg_seconds_per_claim": round(sum(r["seconds"] for r in rows) / n, 2),
        "total_prompt_tokens": sum(r["prompt_tokens"] for r in rows),
        "total_completion_tokens": sum(r["completion_tokens"] for r in rows),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--make-cases", action="store_true")
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--provider", default=None)
    ap.add_argument("--cases", default="data/eval")
    ap.add_argument("--base", default="data/claims/claim_001_clean")
    a = ap.parse_args()
    if a.make_cases:
        make_cases(Path(a.base), Path(a.cases))
        print(f"Created {len(CASES)} labelled cases in {a.cases}")
        return
    policy = json.loads(Path("data/policy.json").read_text())
    history = json.loads(Path("data/claims_history.json").read_text())
    rows = [run_case(d, lambda: LLM(mock=a.mock, provider=a.provider), policy, history)
            for d in sorted(Path(a.cases).iterdir()) if (d / "expected.json").exists()]
    print(f"{'case':<28}{'decision':<20}{'ok':<6}{'flags':<8}{'sec':<6}")
    for r in rows:
        print(f"{r['case']:<28}{r['decision']:<20}{str(r['decision_ok']):<6}{r['flags_found']}/{r['flags_expected']:<6}{r['seconds']:<6}")
    summary = summarise(rows)
    print("\nSUMMARY")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    import os  # optional cost estimate: set PRICE_IN_PER_M and PRICE_OUT_PER_M (price per million tokens, from the Azure pricing page)
    if os.getenv("PRICE_IN_PER_M") and os.getenv("PRICE_OUT_PER_M"):
        cost = (summary["total_prompt_tokens"] * float(os.environ["PRICE_IN_PER_M"]) +
                summary["total_completion_tokens"] * float(os.environ["PRICE_OUT_PER_M"])) / 1_000_000
        print(f"  estimated_cost_total: {cost:.4f}  (per claim: {cost / summary['cases']:.4f})")
    Path("out").mkdir(exist_ok=True)
    Path("out/eval_report.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=2), encoding="utf-8")
    print("\nSaved out/eval_report.json")


if __name__ == "__main__":
    main()
