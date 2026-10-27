import json
from pathlib import Path

from claims_poc.llm import LLM
from claims_poc.orchestrator import process_claim_dir

ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads((ROOT / "data/policy.json").read_text())
HISTORY = json.loads((ROOT / "data/claims_history.json").read_text())


def run(name):
    return process_claim_dir(ROOT / "data/claims" / name, LLM(mock=True), POLICY, HISTORY)


def test_clean_claim_is_partially_approved_with_correct_amount():
    r = run("claim_001_clean")
    assert r["decision"]["decision"] == "PARTIAL_APPROVE"
    # 93000 - 2500 consumables = 90500; less 10% co-pay = 81450
    assert r["decision"]["approved_amount"] == 81450.0
    assert r["decision"]["human_review_required"] is True


def test_suspicious_claim_is_not_approved_and_flags_all_issues():
    r = run("claim_002_suspicious")
    codes = {f["code"] for f in r["findings"]}
    assert r["decision"]["decision"] == "ESCALATE_TO_HUMAN"
    assert r["decision"]["approved_amount"] == 0.0
    assert {"DUPLICATE_BILL", "NAME_MISMATCH", "SPECIFIC_WAITING_PERIOD", "MISSING_DOC"} <= codes


def test_guardrail_blocks_model_approval_when_findings_exist(monkeypatch):
    from claims_poc import agents
    from claims_poc.schemas import Decision
    monkeypatch.setattr(agents, "decide", lambda llm, f, p: Decision(
        decision="APPROVE", reasons=["model says fine"], confidence=0.99))
    r = run("claim_002_suspicious")
    assert r["decision"]["decision"] == "ESCALATE_TO_HUMAN"
    assert r["decision"]["approved_amount"] == 0.0
