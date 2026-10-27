"""Usage:
    python -m claims_poc.main data/claims/claim_001_clean --mock      # offline plumbing test
    python -m claims_poc.main data/claims/claim_001_clean             # real OpenAI calls
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .llm import LLM
from .orchestrator import process_claim_dir, save


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("claim_dir")
    ap.add_argument("--mock", action="store_true", help="no API calls; tests the pipeline only")
    ap.add_argument("--provider", default=None, help="openai or azure (default: env LLM_PROVIDER or openai)")
    ap.add_argument("--policy", default="data/policy.json")
    ap.add_argument("--history", default="data/claims_history.json")
    ap.add_argument("--out", default="out")
    a = ap.parse_args()

    policy = json.loads(Path(a.policy).read_text())
    history = json.loads(Path(a.history).read_text())
    result = process_claim_dir(Path(a.claim_dir), LLM(mock=a.mock, provider=a.provider), policy, history)
    path = save(result, Path(a.out))

    d = result["decision"]
    print(f"\nClaim:    {result['claim_id']}")
    print(f"Decision: {d['decision']}   (human review: {d['human_review_required']}, confidence {d['confidence']})")
    print(f"Claimed:  {d['claimed_amount']}   Approved: {d['approved_amount']}")
    for r in d["reasons"]:
        print(f"  - {r}")
    if d["missing_documents"]:
        print("Missing:", ", ".join(d["missing_documents"]))
    print("Findings:")
    for f in result["findings"]:
        print(f"  [{f['severity']:<7}] {f['agent']:<11} {f['code']}: {f['message']}")
    print(f"\nFull audit trail: {path}")


if __name__ == "__main__":
    main()
