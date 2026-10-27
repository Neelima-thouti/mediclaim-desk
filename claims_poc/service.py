"""Runs one claim end to end and saves the results.
Two engines:
  graph  (default): the LangGraph workflow in graph.py. Gives a step-by-step trace and a real pause for the officer.
  plain           : the simple orchestrator in orchestrator.py (no trace, no pause).
Facts go to SQL (decision, amounts, findings). The full audit JSON goes to Cosmos DB (or local files)."""
from __future__ import annotations

import time

from .documents import bytes_to_text
from .llm import LLM
from .orchestrator import process_claim
from .schemas import DocType


def _load_documents(claim_id: str, repo, blobs) -> list[dict]:
    return [{"filename": fn, "text": bytes_to_text(fn, blobs.get(blob))} for fn, blob in repo.claim_doc_names(claim_id)]


def _persist(claim_id: str, result: dict, repo, audits) -> None:
    audits.save(claim_id, result)          # Cosmos: full JSON trail
    repo.save_result(claim_id, result)     # SQL: decision, amounts, findings
    # Remember this bill so a second claim with the same bill is caught
    bill = next((e for e in result["extracted"] if e["doc_type"] == DocType.HOSPITAL_BILL.value), None)
    is_dup = any(f["code"] == "DUPLICATE_BILL" for f in result["findings"])
    if bill and bill.get("bill_number") and not is_dup:
        repo.register_bill(bill.get("hospital_name"), bill["bill_number"], claim_id, bill.get("total_amount"))


# ---------------------------------------------------------------- plain engine
def run_claim(claim_id: str, repo, blobs, audits, llm: LLM) -> None:
    try:
        claim = repo.get_claim(claim_id)
        policy = repo.get_policy(claim["policy_number"])
        if not policy:
            raise ValueError(f"Unknown policy {claim['policy_number']}")
        repo.set_status(claim_id, "PROCESSING")
        result = process_claim(claim_id, _load_documents(claim_id, repo, blobs), llm, policy,
                               lambda bn: repo.history_for(bn, exclude_claim_id=claim_id))
        result["engine"], result["trace"] = "plain", []
        _persist(claim_id, result, repo, audits)
    except Exception as e:  # keep the API alive; the claim shows FAILED with the reason
        repo.set_status(claim_id, "FAILED", error=f"{type(e).__name__}: {e}"[:500])


# ---------------------------------------------------------------- LangGraph engine
def _trace_note(node: str, update: dict) -> str:
    if node == "classify":
        return f"{len(update['classification'])} documents typed"
    if node == "extract_one":
        e = update["extracted"][0]
        return f"{e['filename']} -> {e['doc_type']}"
    if node == "rules":
        return f"{len(update['rule_findings'])} rule findings; amount payable if approved: {update['payable']['approved']}"
    if node in ("consistency", "coverage", "fraud"):
        return update["reports"][0]["summary"]
    if node == "decide":
        return update["decision"]["decision"]
    return ""


def run_claim_graph(claim_id: str, repo, blobs, audits, llm: LLM, saver) -> None:
    from .graph import build_graph
    try:
        claim = repo.get_claim(claim_id)
        policy = repo.get_policy(claim["policy_number"])
        if not policy:
            raise ValueError(f"Unknown policy {claim['policy_number']}")
        repo.set_status(claim_id, "PROCESSING")
        graph = build_graph(llm, policy, lambda bn: repo.history_for(bn, exclude_claim_id=claim_id), checkpointer=saver)
        cfg = {"configurable": {"thread_id": claim_id}}
        trace, t_prev = [], time.time()
        start = {"claim_id": claim_id, "documents": _load_documents(claim_id, repo, blobs), "extracted": [], "reports": []}
        for chunk in graph.stream(start, cfg, stream_mode="updates"):
            now = time.time()
            for node, update in chunk.items():
                if node == "__interrupt__":
                    trace.append({"step": "human_review", "status": "waiting", "seconds": 0, "note": "paused for the officer"})
                else:
                    trace.append({"step": node, "status": "done", "seconds": round(now - t_prev, 2),
                                  "note": _trace_note(node, update)})
            t_prev = now
        state = graph.get_state(cfg).values
        findings = list(state["rule_findings"]) + [f for r in state["reports"] for f in r["findings"]]
        result = {
            "claim_id": claim_id, "engine": "langgraph", "decision": state["decision"],
            "payable_breakdown": state["payable"], "findings": findings,
            "agent_summaries": {r["agent"]: r["summary"] for r in state["reports"]},
            "classification": [{"filename": fn, "doc_type": t} for fn, t in state["classification"].items()],
            "extracted": sorted(state["extracted"], key=lambda e: e["filename"]),
            "llm_calls": llm.calls, "trace": trace,
        }
        _persist(claim_id, result, repo, audits)
    except Exception as e:
        repo.set_status(claim_id, "FAILED", error=f"{type(e).__name__}: {e}"[:500])


def resume_graph(claim_id: str, repo, audits, saver, reviewer: str, final_decision: str, comment: str) -> bool:
    """Deliver the officer's answer to the paused graph. Returns False if nothing was paused
    (for example the server restarted, because the demo saver keeps state in memory only)."""
    from langgraph.types import Command
    from .graph import build_graph
    policy = repo.get_policy(repo.get_claim(claim_id)["policy_number"])
    graph = build_graph(None, policy, lambda bn: [], checkpointer=saver)   # only the review node runs, so no model is needed
    cfg = {"configurable": {"thread_id": claim_id}}
    if not graph.get_state(cfg).next:
        return False
    graph.invoke(Command(resume={"reviewer": reviewer, "final_decision": final_decision, "comment": comment}), cfg)
    audit = audits.get(claim_id)
    if audit:
        audit["trace"] = [t for t in audit.get("trace", []) if t.get("status") != "waiting"]
        audit["trace"].append({"step": "human_review", "status": "done", "seconds": 0, "note": f"{reviewer}: {final_decision}"})
        audit["human_review"] = {"reviewer": reviewer, "final_decision": final_decision, "comment": comment}
        audits.save(claim_id, audit)
    return True
