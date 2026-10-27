"""Context engineering: decide exactly what goes into the model's window, in what order, within a budget."""
from __future__ import annotations

import json


def approx_tokens(text: str) -> int:
    """Rough rule of thumb: 1 token is about 4 characters of English. For exact counts use the tiktoken library."""
    return max(1, len(text) // 4)


def build_coverage_context(policy: dict, clauses: list[dict], claim_facts: dict, budget_tokens: int = 1200) -> dict:
    """Assemble the coverage agent's context.
    Rules used here:
    1. Stable text first (instructions + policy rules), changing text last. Stable prefixes can be cached.
    2. Retrieved clauses are added best-first until the token budget is used. Dropped ones are recorded.
    3. Only the claim facts the agent needs are included, not whole documents."""
    stable = json.dumps({k: policy[k] for k in ("inception_date", "exclusions", "specific_waiting_days")}, indent=1)
    facts = json.dumps({k: claim_facts.get(k) for k in ("diagnosis", "admission_date")})
    used = approx_tokens(stable) + approx_tokens(facts)
    kept, dropped = [], []
    for c in sorted(clauses, key=lambda c: c["score"], reverse=True):
        cost = approx_tokens(c["text"])
        if used + cost <= budget_tokens:
            kept.append(c)
            used += cost
        else:
            dropped.append(c["chunk_id"])
    return {"policy_rules": stable, "clauses": kept, "claim_facts": facts,
            "dropped_chunk_ids": dropped, "approx_tokens": used, "budget_tokens": budget_tokens}


def to_messages(system: str, ctx: dict, question: str) -> list[dict]:
    """Order matters: system, stable rules, retrieved evidence (cited by id), claim facts, then the question LAST."""
    evidence = "\n\n".join(f"[{c['chunk_id']}] {c['text']}" for c in ctx["clauses"])
    user = (f"<policy_rules>\n{ctx['policy_rules']}\n</policy_rules>\n\n"
            f"<policy_clauses>\n{evidence}\n</policy_clauses>\n\n"
            f"<claim_facts>\n{ctx['claim_facts']}\n</claim_facts>\n\n"
            f"Question: {question}")
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]
