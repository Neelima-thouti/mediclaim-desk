"""Deterministic checks. Maths, dates and lookups are done in code, not by the LLM."""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from .schemas import DocType, ExtractedDoc, Finding

REQUIRED = {"CLAIM_FORM", "HOSPITAL_BILL", "DISCHARGE_SUMMARY", "ID_PROOF"}


def _d(s: Optional[str]) -> Optional[date]:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date() if s else None
    except ValueError:
        return None


def get(docs: list[ExtractedDoc], t: DocType) -> Optional[ExtractedDoc]:
    return next((d for d in docs if d.doc_type == t), None)


def claimed_amount(docs: list[ExtractedDoc]) -> Optional[float]:
    form, bill = get(docs, DocType.CLAIM_FORM), get(docs, DocType.HOSPITAL_BILL)
    return (form.total_amount if form and form.total_amount else None) or (bill.total_amount if bill else None)


def run_rules(docs: list[ExtractedDoc], policy: dict, history: list[dict]) -> tuple[list[Finding], list[str]]:
    out: list[Finding] = []

    def add(sev, code, msg, ev=None):
        out.append(Finding(agent="rules", severity=sev, code=code, message=msg, evidence=ev))

    present = {d.doc_type.value for d in docs}
    missing = sorted(REQUIRED - present)
    for m in missing:
        add("BLOCKER", "MISSING_DOC", f"Required document missing: {m}")

    bill, form, dis = get(docs, DocType.HOSPITAL_BILL), get(docs, DocType.CLAIM_FORM), get(docs, DocType.DISCHARGE_SUMMARY)

    if bill:
        total = sum(li.amount for li in bill.line_items)
        if bill.total_amount is not None and abs(total - bill.total_amount) > 1:
            add("BLOCKER", "BILL_TOTAL_MISMATCH",
                f"Line items add up to {total:.0f} but bill total is {bill.total_amount:.0f}",
                f"difference {bill.total_amount - total:.0f}")
        for li in bill.line_items:
            if li.unit_price is not None and abs(li.quantity * li.unit_price - li.amount) > 1:
                add("WARN", "LINE_ITEM_MATH", f"'{li.description}': qty x price does not equal amount")

    amt_form = form.total_amount if form else None
    if form and bill and amt_form and bill.total_amount and abs(amt_form - bill.total_amount) > 1:
        add("WARN", "CLAIM_VS_BILL_AMOUNT", f"Claim form amount {amt_form:.0f} differs from bill total {bill.total_amount:.0f}")

    for d in docs:
        if d.policy_number and d.policy_number != policy["policy_number"]:
            add("BLOCKER", "POLICY_NUMBER_MISMATCH", f"{d.filename}: policy number {d.policy_number} does not match policy")

    adm = _d((dis.admission_date if dis else None) or (bill.admission_date if bill else None))
    dsc = _d((dis.discharge_date if dis else None) or (bill.discharge_date if bill else None))
    if adm and dsc and dsc < adm:
        add("BLOCKER", "DATES_INVALID", "Discharge date is before admission date")
    if bill and adm and _d(bill.bill_date) and _d(bill.bill_date) < adm:
        add("BLOCKER", "BILL_BEFORE_ADMISSION", "Bill is dated before admission")

    if adm:
        start, end = _d(policy["current_period_start"]), _d(policy["current_period_end"])
        if not (start <= adm <= end):
            add("BLOCKER", "POLICY_NOT_ACTIVE", f"Admission {adm} is outside policy period {start} to {end}")
        days_since_inception = (adm - _d(policy["inception_date"])).days
        if days_since_inception < policy["initial_waiting_days"]:
            add("WARN", "INITIAL_WAITING_PERIOD",
                f"Admission is {days_since_inception} days after inception (waiting {policy['initial_waiting_days']} days). "
                "Accident cases are exempt, so a human must check.")

    sub = _d(form.submission_date) if form else None
    if sub and dsc and (sub - dsc).days > policy["claim_intimation_days"]:
        add("WARN", "LATE_SUBMISSION", f"Claim filed {(sub - dsc).days} days after discharge (limit {policy['claim_intimation_days']})")

    if bill and bill.bill_number:
        for h in history:
            if h["bill_number"].lower() == bill.bill_number.lower() and \
               (bill.hospital_name or "").lower() == h["hospital"].lower():
                add("BLOCKER", "DUPLICATE_BILL", f"Bill {bill.bill_number} was already claimed in {h['claim_id']}",
                    f"earlier amount {h['amount']}")

    ca = claimed_amount(docs)
    if ca and ca > policy["sum_insured"]:
        add("WARN", "EXCEEDS_SUM_INSURED", f"Claimed {ca:.0f} exceeds sum insured {policy['sum_insured']}")
    return out, missing


def compute_payable(docs: list[ExtractedDoc], policy: dict) -> dict:
    """Simplified payable calculation. Real policies have more rules (see README)."""
    bill = get(docs, DocType.HOSPITAL_BILL)
    if not bill:
        return {"claimed": claimed_amount(docs), "approved": 0.0, "deductions": [], "note": "no bill"}
    cap = policy["room_rent_cap_per_day"]
    payable, deductions = 0.0, []
    for li in bill.line_items:
        ok = li.amount
        if li.category in policy["non_payable_categories"]:
            deductions.append({"item": li.description, "reason": "non-payable category", "amount": li.amount})
            ok = 0.0
        elif li.category == "ROOM":
            rate = li.unit_price or (li.amount / max(li.quantity, 1))
            if rate > cap:
                ok = cap * li.quantity
                deductions.append({"item": li.description, "reason": f"room rent above cap {cap}/day",
                                   "amount": li.amount - ok})
        payable += ok
    copay = payable * policy["copay_percent"] / 100
    if copay:
        deductions.append({"item": "co-payment", "reason": f"{policy['copay_percent']}% co-pay", "amount": copay})
    approved = min(payable - copay, policy["sum_insured"])
    return {"claimed": claimed_amount(docs) or bill.total_amount, "payable_before_copay": payable,
            "approved": round(approved, 2), "deductions": deductions}
