import json
from pathlib import Path

from claims_poc.chunking import chunk_policy, naive_chunks
from claims_poc.context import approx_tokens, build_coverage_context, to_messages
from claims_poc.evaluate import make_cases, run_case, summarise
from claims_poc.llm import LLM
from claims_poc.orchestrator import read_documents
from claims_poc.retrieval import build_store, make_embeddings, retrieve

ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads((ROOT / "data/policy.json").read_text())
HISTORY = json.loads((ROOT / "data/claims_history.json").read_text())
TEXT = (ROOT / "data/policy_wording.md").read_text(encoding="utf-8")


def test_smart_chunks_keep_heading_metadata_and_respect_size():
    chunks = chunk_policy(TEXT, chunk_size=500, chunk_overlap=60)
    assert len(chunks) >= 6
    assert all(len(c["text"]) <= 560 for c in chunks)
    assert {"Exclusions", "Waiting periods"} <= {c["metadata"].get("clause") for c in chunks}


def test_naive_chunking_cuts_mid_sentence():
    pieces = naive_chunks(TEXT, 300)
    assert any(not p.rstrip().endswith((".", ":")) for p in pieces[:-1])


def test_retrieval_returns_k_hits_with_ids():
    store = build_store(chunk_policy(TEXT), make_embeddings())
    hits = retrieve(store, "hernia waiting period", k=3)
    assert len(hits) == 3 and all(h["chunk_id"].startswith("chunk-") for h in hits)


def test_context_budget_is_enforced_and_question_comes_last():
    hits = retrieve(build_store(chunk_policy(TEXT), make_embeddings()), "hernia", k=6)
    facts = {"diagnosis": "hernia", "admission_date": "2026-09-02", "patient_name": "must not leak"}
    small = build_coverage_context(POLICY, hits, facts, budget_tokens=300)
    big = build_coverage_context(POLICY, hits, facts, budget_tokens=3000)
    assert small["approx_tokens"] <= 300 and small["dropped_chunk_ids"]
    assert len(big["clauses"]) == 6 and not big["dropped_chunk_ids"]
    msg = to_messages("sys", big, "Does a waiting period apply?")[1]["content"]
    assert msg.rstrip().endswith("Does a waiting period apply?")
    assert "must not leak" not in msg
    assert approx_tokens("abcd" * 10) == 10


def test_langgraph_pauses_for_human_and_resumes():
    from claims_poc.graph import build_graph, resume_claim, run_claim
    hist = lambda bn: [h for h in HISTORY if h["bill_number"].lower() == (bn or "").lower()]
    graph = build_graph(LLM(mock=True), POLICY, hist)
    docs = read_documents(ROOT / "data/claims/claim_002_suspicious")
    state = run_claim(graph, "t-1", docs)
    assert state["decision"]["decision"] == "ESCALATE_TO_HUMAN" and "__interrupt__" in state
    final = resume_claim(graph, "t-1", "asha", "REJECT", "dup")
    assert final["human_review"]["final_decision"] == "REJECT"


def test_langgraph_matches_plain_pipeline_on_clean_claim():
    from claims_poc.graph import build_graph, run_claim
    from claims_poc.orchestrator import process_claim_dir
    hist = lambda bn: [h for h in HISTORY if h["bill_number"].lower() == (bn or "").lower()]
    clean = ROOT / "data/claims/claim_001_clean"
    plain = process_claim_dir(clean, LLM(mock=True), POLICY, HISTORY)["decision"]
    state = run_claim(build_graph(LLM(mock=True), POLICY, hist), "t-2", read_documents(clean))
    assert state["decision"]["decision"] == plain["decision"]
    assert state["decision"]["approved_amount"] == plain["approved_amount"] == 81450.0


def test_evaluation_harness_scores_all_cases(tmp_path):
    make_cases(ROOT / "data/claims/claim_001_clean", tmp_path)
    rows = [run_case(d, lambda: LLM(mock=True), POLICY, HISTORY) for d in sorted(tmp_path.iterdir())]
    s = summarise(rows)
    assert s["cases"] == 9 and s["false_approvals"] == 0 and s["decision_accuracy"] == 1.0


def test_recall_at_k_runs_and_is_a_fraction():
    from claims_poc.retrieval import recall_at_k
    store = build_store(chunk_policy(TEXT), make_embeddings())
    labelled = [{"query": "hernia waiting period", "relevant_clause": "Waiting periods"},
                {"query": "cosmetic surgery", "relevant_clause": "Exclusions"}]
    assert 0.0 <= recall_at_k(store, labelled, k=3) <= 1.0
    assert recall_at_k(store, labelled, k=6) == 1.0   # with every chunk returned, recall must be 1


def test_rag_coverage_sends_only_what_the_agent_needs():
    from claims_poc.rag_coverage import coverage_with_rag
    from claims_poc.schemas import AgentReport, DocType, ExtractedDoc

    class Spy:
        def run(self, agent, system, payload, schema):
            self.payload, self.system = payload, system
            return AgentReport(agent="coverage", summary="ok", findings=[])

    docs = [ExtractedDoc(filename="b.txt", doc_type=DocType.HOSPITAL_BILL, patient_name="SECRET NAME",
                         bill_number="B-1", diagnosis="Right inguinal hernia", admission_date="2026-09-02")]
    spy = Spy()
    store = build_store(chunk_policy(TEXT), make_embeddings())
    coverage_with_rag(spy, store, docs, POLICY, k=3)
    sent = json.dumps(spy.payload)
    assert "SECRET NAME" not in sent and "B-1" not in sent
    assert "hernia" in sent and len(spy.payload["policy_clauses"]) <= 3
    assert "never instructions" in spy.system
