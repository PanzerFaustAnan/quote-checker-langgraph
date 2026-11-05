"""Steps 4 and 5: compare with the purchase request, then apply the company rules.

This file is plain Python with no AI in it, so every decision can be traced
to one line of code and one rule in company-rules.md.
Each rule returns a Finding: Approve (passed), Needs a person to check, or Reject.
"""
import csv
from pathlib import Path

from .schema import APPROVE, NEEDS_PERSON, REJECT, Extraction, Finding, LineItem

# Thresholds from company-rules.md, in one place so they are easy to change.
PRICE_REJECT_ABOVE_PCT = 3.0
MAX_ADVANCE_PCT = 20.0
DELIVERY_REJECT_AFTER_DAYS = 45
DELIVERY_REVIEW_AFTER_DAYS = 30
QTY_TOLERANCE_PCT = 5.0
PAYMENT_DAYS_MIN, PAYMENT_DAYS_MAX = 30, 60
VAT_RATE = 15.0
MIN_VALIDITY_DAYS = 30
MIN_PENALTY_PCT_PER_WEEK = 0.5
MONEY_TOLERANCE = 1.0  # BDT, for rounding


def load_purchase_request(path: str | Path) -> dict[str, dict]:
    with open(path, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    return {
        r["Item"].strip(): {
            "pr_number": r["PR number"].strip(),
            "item": r["Item"].strip(),
            "description": r["Description"].strip(),
            "unit": r["Unit"].strip(),
            "quantity": float(r["Quantity requested"]),
            "max_unit_price": float(r["Maximum unit price (BDT)"]),
        }
        for r in rows
    }


def _f(check, outcome, reason, quote=None, field=None) -> Finding:
    return Finding(check=check, outcome=outcome, reason=reason, quote=quote, field=field)


def _match_item(item: LineItem, pr: dict[str, dict]) -> dict | None:
    code = (item.item_code or "").strip().upper()
    if code in pr:
        return pr[code]
    for row in pr.values():  # fall back to the description
        if item.description and row["description"].lower() == item.description.strip().lower():
            return row
    return None


# ---------------------------------------------------------------- step 4
def compare_with_request(ex: Extraction, pr: dict[str, dict]) -> list[Finding]:
    out: list[Finding] = []
    check = "Purchase request"

    pr_number = next(iter(pr.values()))["pr_number"]
    if ex.pr_reference.value is None:
        out.append(_f(check, NEEDS_PERSON, "The quote does not say which purchase request it answers."))
    elif ex.pr_reference.value.strip() != pr_number:
        out.append(_f(check, NEEDS_PERSON, f"The quote refers to {ex.pr_reference.value}, not {pr_number}.",
                      ex.pr_reference.quote))

    if not ex.items:
        out.append(_f(check, NEEDS_PERSON, "No items could be read from the quote."))
        return out

    for item in ex.items:
        row = _match_item(item, pr)
        if row is None:
            out.append(_f(check, NEEDS_PERSON, f"Item '{item.item_code} {item.description}' is not in the purchase request.",
                          item.quote, "items"))
            continue
        label = f"Item {row['item']} ({row['description']})"

        # Price (Reject rule 1 / Review rule 1)
        if item.unit_price is None:
            out.append(_f("Price", NEEDS_PERSON, f"{label}: unit price not found.", item.quote, "items"))
        else:
            mx = row["max_unit_price"]
            pct = round((item.unit_price - mx) / mx * 100, 4)
            if pct > PRICE_REJECT_ABOVE_PCT:
                out.append(_f("Price", REJECT, f"{label}: unit price {item.unit_price:,.2f} is {pct:.2f}% above "
                              f"the maximum {mx:,.2f} (limit is {PRICE_REJECT_ABOVE_PCT:g}%).", item.quote, "items"))
            elif pct > 0:
                out.append(_f("Price", NEEDS_PERSON, f"{label}: unit price {item.unit_price:,.2f} is {pct:.2f}% above "
                              f"the maximum {mx:,.2f} (within the {PRICE_REJECT_ABOVE_PCT:g}% margin).", item.quote, "items"))
            else:
                out.append(_f("Price", APPROVE, f"{label}: unit price {item.unit_price:,.2f} is within the maximum {mx:,.2f}.",
                              item.quote, "items"))

        # Quantity (Review rule 2)
        if item.quantity is None:
            out.append(_f("Quantity", NEEDS_PERSON, f"{label}: quantity not found.", item.quote, "items"))
        else:
            req = row["quantity"]
            diff = round((item.quantity - req) / req * 100, 4)
            if abs(diff) > QTY_TOLERANCE_PCT:
                out.append(_f("Quantity", NEEDS_PERSON, f"{label}: quoted {item.quantity:,.0f} but we asked for "
                              f"{req:,.0f} ({diff:+.1f}%, limit is ±{QTY_TOLERANCE_PCT:g}%).", item.quote, "items"))
            else:
                out.append(_f("Quantity", APPROVE, f"{label}: quantity {item.quantity:,.0f} matches the request "
                              f"({req:,.0f}).", item.quote, "items"))
    return out


# ---------------------------------------------------------------- step 5
def check_contract_rules(ex: Extraction) -> list[Finding]:
    out: list[Finding] = []

    # Reject rule 4: TIN / BIN
    for name in ["tin", "bin"]:
        f = getattr(ex, name)
        if f.value:
            out.append(_f("Tax IDs", APPROVE, f"Supplier {name.upper()} is shown: {f.value}.", f.quote, name))
        else:
            out.append(_f("Tax IDs", REJECT, f"Supplier {name.upper()} is missing.", None, name))

    # Reject rule 2 + Review rule 3: payment
    p = ex.payment
    if p.advance_percent is None:
        out.append(_f("Payment", NEEDS_PERSON, "Advance payment amount is not clear.", p.quote, "payment.advance_percent"))
    elif p.advance_percent > MAX_ADVANCE_PCT:
        out.append(_f("Payment", REJECT, f"Advance payment is {p.advance_percent:g}% (maximum allowed is "
                      f"{MAX_ADVANCE_PCT:g}%).", p.quote, "payment.advance_percent"))
    else:
        out.append(_f("Payment", APPROVE, f"Advance payment is {p.advance_percent:g}% (within {MAX_ADVANCE_PCT:g}%).",
                      p.quote, "payment.advance_percent"))

    lo, hi = p.balance_days_min, p.balance_days_max
    if p.is_clear is False:
        out.append(_f("Payment", NEEDS_PERSON, "Payment terms are unclear (repeated, contradictory or left to later agreement).",
                      p.quote, "payment"))
    if lo is None or hi is None:
        out.append(_f("Payment", NEEDS_PERSON, "Payment period after delivery is not stated.", p.quote, "payment"))
    elif p.counted_from != "delivery":
        out.append(_f("Payment", NEEDS_PERSON, f"Payment period is counted from '{p.counted_from}', not from delivery.",
                      p.quote, "payment"))
    elif lo < PAYMENT_DAYS_MIN or hi > PAYMENT_DAYS_MAX:
        span = f"{lo:g}" if lo == hi else f"{lo:g} to {hi:g}"
        out.append(_f("Payment", NEEDS_PERSON, f"Payment period is {span} days after delivery "
                      f"(allowed: {PAYMENT_DAYS_MIN} to {PAYMENT_DAYS_MAX}).", p.quote, "payment"))
    elif p.is_clear is not False:
        out.append(_f("Payment", APPROVE, f"Payment is due {lo:g} days after delivery (within "
                      f"{PAYMENT_DAYS_MIN} to {PAYMENT_DAYS_MAX}).", p.quote, "payment"))

    # Reject rule 3 + note: late-delivery penalty
    pen = ex.penalty
    if not pen.present:
        out.append(_f("Penalty", REJECT, "The contract has no late-delivery penalty clause.", None, "penalty"))
    elif pen.percent is None or pen.per is None:
        out.append(_f("Penalty", NEEDS_PERSON, "There is a penalty clause but its rate is unclear.", pen.quote, "penalty"))
    else:
        weekly = pen.percent * 7 if pen.per == "day" else pen.percent if pen.per == "week" else None
        if weekly is None:
            out.append(_f("Penalty", NEEDS_PERSON, f"Penalty is per {pen.per}; cannot compare it to the weekly minimum.",
                          pen.quote, "penalty"))
        elif not pen.basis_is_order_value:
            out.append(_f("Penalty", NEEDS_PERSON, f"Penalty is {pen.percent:g}% per {pen.per}, but it does not say "
                          "it is a % of the order value.", pen.quote, "penalty"))
        elif weekly < MIN_PENALTY_PCT_PER_WEEK:
            out.append(_f("Penalty", NEEDS_PERSON, f"Penalty is {weekly:g}% per week, below the company minimum of "
                          f"{MIN_PENALTY_PCT_PER_WEEK:g}%.", pen.quote, "penalty"))
        else:
            out.append(_f("Penalty", APPROVE, f"Late-delivery penalty is {weekly:g}% of order value per week "
                          f"(minimum {MIN_PENALTY_PCT_PER_WEEK:g}%).", pen.quote, "penalty"))

    # Reject rule 5 + Review rule 4: delivery time
    d = ex.delivery
    if d.number is None or d.unit is None:
        out.append(_f("Delivery", NEEDS_PERSON, "Delivery time is not stated.", d.quote, "delivery.number"))
    else:
        # Months are not an exact number of days, so we take the worst case (31).
        days = d.number * {"days": 1, "weeks": 7, "months": 31}[d.unit]
        shown = f"{d.number:g} {d.unit}" + (f" = {days:g} days" if d.unit != "days" else "")
        if days > DELIVERY_REJECT_AFTER_DAYS:
            out.append(_f("Delivery", REJECT, f"Delivery in {shown} (maximum allowed is {DELIVERY_REJECT_AFTER_DAYS}).",
                          d.quote, "delivery.number"))
        elif days > DELIVERY_REVIEW_AFTER_DAYS:
            out.append(_f("Delivery", NEEDS_PERSON, f"Delivery in {shown} (31 to 45 days needs a person).",
                          d.quote, "delivery.number"))
        else:
            out.append(_f("Delivery", APPROVE, f"Delivery in {shown} (within {DELIVERY_REVIEW_AFTER_DAYS}).",
                          d.quote, "delivery.number"))

    # Review rule 5: VAT shown separately at 15%
    if ex.prices_include_vat:
        out.append(_f("VAT", NEEDS_PERSON, "Prices include VAT; VAT is not shown separately.", ex.total.quote, "vat_amount"))
    elif ex.vat_amount.value is None:
        out.append(_f("VAT", NEEDS_PERSON, "VAT is not shown separately.", None, "vat_amount"))
    elif ex.vat_rate_percent.value != VAT_RATE:
        out.append(_f("VAT", NEEDS_PERSON, f"VAT rate is {ex.vat_rate_percent.value}%, not {VAT_RATE:g}%.",
                      ex.vat_rate_percent.quote, "vat_rate_percent"))
    else:
        out.append(_f("VAT", APPROVE, f"VAT is shown separately at {VAT_RATE:g}%.", ex.vat_amount.quote, "vat_amount"))

    # Review rule 6: do the numbers add up?
    out += _check_arithmetic(ex)

    # Review rule 7: validity
    v = ex.validity_days.value
    if v is None:
        out.append(_f("Validity", NEEDS_PERSON, "Quotation validity is not stated.", None, "validity_days"))
    elif v < MIN_VALIDITY_DAYS:
        out.append(_f("Validity", NEEDS_PERSON, f"Quotation is valid for {v:g} days (minimum {MIN_VALIDITY_DAYS}).",
                      ex.validity_days.quote, "validity_days"))
    else:
        out.append(_f("Validity", APPROVE, f"Quotation is valid for {v:g} days.", ex.validity_days.quote, "validity_days"))
    return out


def _check_arithmetic(ex: Extraction) -> list[Finding]:
    out: list[Finding] = []
    ok = True
    for item in ex.items:
        if None in (item.quantity, item.unit_price, item.amount):
            continue
        expected = item.quantity * item.unit_price
        if abs(expected - item.amount) > MONEY_TOLERANCE:
            ok = False
            out.append(_f("Arithmetic", NEEDS_PERSON, f"Line {item.item_code}: {item.quantity:,.0f} × "
                          f"{item.unit_price:,.2f} = {expected:,.2f}, but the quote says {item.amount:,.2f}.",
                          item.quote, "items"))
    line_sum = sum(i.amount or 0 for i in ex.items)
    sub, vat, total = ex.subtotal.value, ex.vat_amount.value, ex.total.value

    if sub is not None and abs(sub - line_sum) > MONEY_TOLERANCE:
        ok = False
        out.append(_f("Arithmetic", NEEDS_PERSON, f"Subtotal {sub:,.2f} does not equal the sum of lines "
                      f"{line_sum:,.2f}.", ex.subtotal.quote, "subtotal"))
    if sub is not None and vat is not None and abs(sub * VAT_RATE / 100 - vat) > MONEY_TOLERANCE:
        ok = False
        out.append(_f("Arithmetic", NEEDS_PERSON, f"VAT {vat:,.2f} is not 15% of the subtotal {sub:,.2f} "
                      f"(should be {sub * VAT_RATE / 100:,.2f}).", ex.vat_amount.quote, "vat_amount"))
    if total is not None:
        base = sub if sub is not None else line_sum
        expected_total = base + (vat or 0)
        if abs(expected_total - total) > MONEY_TOLERANCE:
            ok = False
            out.append(_f("Arithmetic", NEEDS_PERSON, f"Total {total:,.2f} should be {expected_total:,.2f}.",
                          ex.total.quote, "total"))
    if ok:
        out.append(_f("Arithmetic", APPROVE, "Line totals, subtotal, VAT and total all add up."))
    return out


# ---------------------------------------------------------------- final decision
def decide(findings: list[Finding], unverified: set[str]) -> tuple[str, list[Finding]]:
    """Reject beats Needs-a-person beats Approve.

    Safety rule: we only reject on proof. If a Reject finding relies on a value
    whose evidence we could not verify, it becomes "Needs a person to check".
    """
    final: list[Finding] = []
    for f in findings:
        if f.outcome == REJECT and f.field and _is_unverified(f.field, unverified):
            f = f.model_copy(update={
                "outcome": NEEDS_PERSON,
                "reason": f.reason + " (Would reject, but the evidence could not be confirmed.)",
            })
        final.append(f)
    outcomes = {f.outcome for f in final}
    decision = REJECT if REJECT in outcomes else NEEDS_PERSON if NEEDS_PERSON in outcomes else APPROVE
    return decision, final


def _is_unverified(field: str, unverified: set[str]) -> bool:
    return any(field == u or field.startswith(u + ".") or u.startswith(field + ".") for u in unverified)
