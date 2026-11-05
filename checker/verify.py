"""Step 3: check the AI's evidence.

For every value the AI returned, It checks two things in plain Python:
  1. the quote it gave is really in the document, word for word;
  2. the number it gave really appears inside that quote.
If either fails, we do not trust that value.

"""
import re

from .schema import NEEDS_PERSON, Extraction, Finding

_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def normalise(s: str) -> str:
    s = s.lower().replace("’", "'").replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", s).strip()


def quote_in_document(quote: str, text: str) -> bool:
    q, t = normalise(quote), normalise(text)
    if q in t:
        return True
    # allow the AI to drop thousands separators ("12000" vs "12,000")
    return q.replace(",", "") in t.replace(",", "")


def numbers_in(quote: str) -> list[float]:
    return [float(m.replace(",", "")) for m in _NUMBER.findall(quote)]


def number_in_quote(value: float, quote: str) -> bool:
    if value == 0 and re.search(r"\b(no|nil|not|none|without)\b", quote.lower()):
        return True  # "No advance payment required" -> 0
    return any(abs(n - value) < 0.005 for n in numbers_in(quote))


def _fields_to_check(ex: Extraction):
    """Yield (field name, value, quote, is_number) for everything the AI filled in."""
    for name in ["supplier_name", "quotation_no", "quote_date", "pr_reference", "tin", "bin"]:
        f = getattr(ex, name)
        yield name, f.value, f.quote, False
    for name in ["subtotal", "vat_rate_percent", "vat_amount", "total", "validity_days"]:
        f = getattr(ex, name)
        yield name, f.value, f.quote, True
    for i, item in enumerate(ex.items):
        for attr in ["quantity", "unit_price", "amount"]:
            yield f"items[{i}].{attr}", getattr(item, attr), item.quote, True
    p = ex.payment
    yield "payment.advance_percent", p.advance_percent, p.quote, True
    yield "payment.balance_days_min", p.balance_days_min, p.quote, True
    yield "payment.balance_days_max", p.balance_days_max, p.quote, True
    yield "delivery.number", ex.delivery.number, ex.delivery.quote, True
    if ex.penalty.present:
        yield "penalty.percent", ex.penalty.percent, ex.penalty.quote, True


def verify_evidence(ex: Extraction, text: str) -> tuple[list[Finding], set[str], int]:
    """Return (problems found, names of fields we could not verify, number of fields checked)."""
    problems: list[Finding] = []
    unverified: set[str] = set()
    checked = 0

    for name, value, quote, is_number in _fields_to_check(ex):
        if value is None:
            continue
        checked += 1
        ok, why = True, ""
        if not quote:
            ok, why = False, "the AI gave no quote for it"
        elif not quote_in_document(quote, text):
            ok, why = False, "the quote the AI gave is not in the document"
        elif is_number and not number_in_quote(float(value), quote):
            ok, why = False, f"the number {value:g} is not in the quoted text"
        elif not is_number and normalise(str(value)) not in normalise(quote):
            ok, why = False, f"'{value}' is not in the quoted text"
        if not ok:
            unverified.add(name.split(".")[0].split("[")[0] if name.startswith("items") else name)
            problems.append(Finding(
                check="Evidence check", outcome=NEEDS_PERSON, field=name,
                reason=f"Could not confirm {name} = {value}: {why}.", quote=quote,
            ))

    # Double-check "missing" claims that would cause a rejection.
    t = normalise(text)
    absence_checks = [
        ("tin", ex.tin.value is None, r"\btin\b"),
        ("bin", ex.bin.value is None, r"\bbin\b"),
        # Suppliers do not always use the word "penalty" (see pack 02), so look for delay wording too.
        ("penalty", not ex.penalty.present, r"penalt|liquidated damage|late delivery|delay in delivery|per week of delay"),
    ]
    for field, ai_says_missing, pattern in absence_checks:
        if ai_says_missing and re.search(pattern, t):
            unverified.add(field)
            problems.append(Finding(
                check="Evidence check", outcome=NEEDS_PERSON, field=field,
                reason=f"The AI says the {field.upper() if field != 'penalty' else 'penalty clause'} is missing, "
                       f"but the document mentions it. A person should look.",
            ))
    return problems, unverified, checked
