"""The claim pipeline rebuilt as a LangGraph graph.
Same agents, same rules, same guardrails as orchestrator.py. What LangGraph adds:
state with reducers, fan-out/fan-in, checkpoints (pause and resume), and human-in-the-loop interrupts."""
from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, Send, interrupt

from . import agents
from .llm import LLM
from .orchestrator import apply_guardrails
from .rules import claimed_amount, compute_payable, run_rules
from .schemas import AgentReport, Decision, DocType, ExtractedDoc, Finding


class ClaimState(TypedDict, total=False):
    # Keep state as plain dicts and lists: it must be serialisable so it can be saved at each step.
    claim_id: str
    documents: list[dict]
    classification: dict                              # filename -> doc type
    extracted: Annotated[list[dict], operator.add]    # reducer: parallel branches APPEND instead of overwrite
    rule_findings: list[dict]
    payable: dict
    missing: list[str]
    reports: Annotated[list[dict], operator.add]
    decision: dict
    human_review: dict


def build_graph(llm: LLM, policy: dict, history_fn, checkpointer=None):
    def classify(state: ClaimState):
        docs = [d for d in state["documents"] if d.get("text")]
        result = agents.classify(llm, docs)
        return {"classification": {c.filename: c.doc_type.value for c in result.docs}}

    def fan_out_extract(state: ClaimState):
        """Conditional edge that returns one Send per document: a map step. Each runs the same node in parallel."""
        return [Send("extract_one", {"doc": d, "doc_type": state["classification"][d["filename"]]})
                for d in state["documents"] if d.get("text")]

    def extract_one(payload: dict):
        d = payload["doc"]
        e = agents.extract(llm, d["filename"], payload["doc_type"], d["text"])
        e.doc_type = DocType(payload["doc_type"])
        return {"extracted": [e.model_dump(mode="json")]}

    def _docs(state) -> list[ExtractedDoc]:
        return [ExtractedDoc.model_validate(x) for x in state["extracted"]]

    def rules(state: ClaimState):
        docs = _docs(state)
        bill = next((e for e in docs if e.doc_type == DocType.HOSPITAL_BILL), None)
        history = history_fn(bill.bill_number) if bill and bill.bill_number else []
        findings, missing = run_rules(docs, policy, history)
        unreadable = [d["filename"] for d in state["documents"] if not d.get("text")]
        for name in unreadable:
            findings.append(Finding(agent="rules", severity="WARN", code="UNREADABLE_DOC",
                                    message=f"{name} could not be read (scanned or unsupported). OCR is needed."))
        return {"rule_findings": [f.model_dump() for f in findings], "missing": missing,
                "payable": compute_payable(docs, policy)}

    def consistency(state: ClaimState):
        return {"reports": [agents.consistency(llm, _docs(state)).model_dump()]}

    def coverage(state: ClaimState):
        return {"reports": [agents.coverage(llm, _docs(state), policy).model_dump()]}

    def fraud(state: ClaimState):
        rf = [Finding.model_validate(f) for f in state["rule_findings"]]
        docs = _docs(state)
        bill = next((e for e in docs if e.doc_type == DocType.HOSPITAL_BILL), None)
        history = history_fn(bill.bill_number) if bill and bill.bill_number else []
        return {"reports": [agents.fraud(llm, docs, rf, history).model_dump()]}

    def decide(state: ClaimState):
        findings = [Finding.model_validate(f) for f in state["rule_findings"]]
        for r in state["reports"]:
            findings += [Finding.model_validate(f) for f in r["findings"]]
        decision = agents.decide(llm, findings, state["payable"])
        decision = apply_guardrails(decision, findings, state["payable"], state["missing"], claimed_amount(_docs(state)))
        return {"decision": decision.model_dump()}

    def needs_human(state: ClaimState):
        return "human_review" if state["decision"]["human_review_required"] else END

    def human_review(state: ClaimState):
        """interrupt() PAUSES the graph here and hands this payload to the caller.
        The state is saved by the checkpointer. Resuming with Command(resume=...) returns that value here."""
        answer = interrupt({"claim_id": state["claim_id"], "ai_decision": state["decision"]["decision"],
                            "reasons": state["decision"]["reasons"]})
        return {"human_review": answer}

    g = StateGraph(ClaimState)
    for name, fn in [("classify", classify), ("extract_one", extract_one), ("rules", rules),
                     ("consistency", consistency), ("coverage", coverage), ("fraud", fraud),
                     ("decide", decide), ("human_review", human_review)]:
        g.add_node(name, fn)
    g.add_edge(START, "classify")
    g.add_conditional_edges("classify", fan_out_extract, ["extract_one"])
    g.add_edge("extract_one", "rules")                       # runs once, after ALL extract_one branches finish
    for name in ("consistency", "coverage", "fraud"):
        g.add_edge("rules", name)                            # fan-out: three branches in parallel
    g.add_edge(["consistency", "coverage", "fraud"], "decide")   # fan-in: wait for all three
    g.add_conditional_edges("decide", needs_human, ["human_review", END])
    g.add_edge("human_review", END)
    return g.compile(checkpointer=checkpointer or InMemorySaver())


def run_claim(graph, claim_id: str, documents: list[dict]) -> dict:
    """Start (or continue) a claim. If the graph pauses for a human, the result contains '__interrupt__'."""
    cfg = {"configurable": {"thread_id": claim_id}}
    return graph.invoke({"claim_id": claim_id, "documents": documents, "extracted": [], "reports": []}, cfg)


def resume_claim(graph, claim_id: str, reviewer: str, final_decision: str, comment: str = "") -> dict:
    cfg = {"configurable": {"thread_id": claim_id}}
    return graph.invoke(Command(resume={"reviewer": reviewer, "final_decision": final_decision, "comment": comment}), cfg)
