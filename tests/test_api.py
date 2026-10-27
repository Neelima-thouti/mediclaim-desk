from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from claims_poc.api import create_app
from claims_poc.db import Repo, make_engine
from claims_poc.llm import LLM
from claims_poc.stores import LocalAuditStore, LocalBlobStore

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(params=["graph", "plain"])
def client(tmp_path, request):
    repo = Repo(make_engine(f"sqlite:///{tmp_path}/t.db"))
    app = create_app(repo, LocalBlobStore(tmp_path / "blobs"), LocalAuditStore(tmp_path / "audit"),
                     llm_factory=lambda: LLM(mock=True), seed_demo=True, engine=request.param)
    return TestClient(app)


def submit(client, name):
    files = [("files", (p.name, p.read_bytes(), "text/plain")) for p in sorted((ROOT / "data/claims" / name).glob("*.txt"))]
    r = client.post("/claims", data={"policy_number": "POL-123456"}, files=files)
    assert r.status_code == 202
    return r.json()["claim_id"]


def test_clean_claim_flow(client):
    cid = submit(client, "claim_001_clean")
    c = client.get(f"/claims/{cid}").json()
    assert c["status"] == "AWAITING_REVIEW" and c["ai_decision"] == "PARTIAL_APPROVE"
    assert c["approved_amount"] == 81450.0
    assert client.get(f"/claims/{cid}/audit").json()["claim_id"] == cid


def test_seeded_history_flags_duplicate_and_fraud_goes_to_human(client):
    cid = submit(client, "claim_002_suspicious")
    c = client.get(f"/claims/{cid}").json()
    assert c["ai_decision"] == "ESCALATE_TO_HUMAN" and c["approved_amount"] == 0.0
    assert "DUPLICATE_BILL" in {f["code"] for f in c["findings"]}


def test_resubmitting_same_bill_is_caught_via_sql(client):
    first = submit(client, "claim_001_clean")
    second = submit(client, "claim_001_clean")
    codes = {f["code"] for f in client.get(f"/claims/{second}").json()["findings"]}
    assert "DUPLICATE_BILL" in codes
    assert "DUPLICATE_BILL" not in {f["code"] for f in client.get(f"/claims/{first}").json()["findings"]}


def test_human_review_closes_the_claim(client):
    cid = submit(client, "claim_001_clean")
    r = client.post(f"/claims/{cid}/review", json={"reviewer": "asha", "final_decision": "PARTIAL_APPROVE", "comment": "ok"})
    assert r.status_code == 200 and r.json()["status"] == "COMPLETED"
    assert client.post(f"/claims/{cid}/review", json={"reviewer": "x", "final_decision": "REJECT"}).status_code == 409


def test_rejects_unknown_policy_and_bad_file_type(client):
    assert client.post("/claims", data={"policy_number": "NOPE"}, files=[("files", ("a.txt", b"x", "text/plain"))]).status_code == 404
    assert client.post("/claims", data={"policy_number": "POL-123456"}, files=[("files", ("a.exe", b"x", "application/octet-stream"))]).status_code == 422


def test_graph_engine_records_a_trace_and_resumes_after_review(tmp_path):
    repo = Repo(make_engine(f"sqlite:///{tmp_path}/t.db"))
    c = TestClient(create_app(repo, LocalBlobStore(tmp_path / "b"), LocalAuditStore(tmp_path / "a"),
                              llm_factory=lambda: LLM(mock=True), seed_demo=True, engine="graph"))
    cid = submit(c, "claim_002_suspicious")
    audit = c.get(f"/claims/{cid}/audit").json()
    steps = [t["step"] for t in audit["trace"]]
    assert steps[0] == "classify" and "rules" in steps and "decide" in steps and steps[-1] == "human_review"
    assert audit["trace"][-1]["status"] == "waiting" and audit["engine"] == "langgraph"
    c.post(f"/claims/{cid}/review", json={"reviewer": "asha", "final_decision": "REJECT", "comment": "duplicate"})
    audit = c.get(f"/claims/{cid}/audit").json()
    assert audit["trace"][-1]["status"] == "done" and audit["human_review"]["reviewer"] == "asha"


def test_list_meta_and_cors(client):
    submit(client, "claim_001_clean")
    rows = client.get("/claims").json()
    assert len(rows) == 1 and rows[0]["status"] == "AWAITING_REVIEW"
    assert client.get("/meta").json()["llm_provider"] in ("mock", "openai", "azure")
    r = client.get("/health", headers={"Origin": "http://localhost:5173"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"
