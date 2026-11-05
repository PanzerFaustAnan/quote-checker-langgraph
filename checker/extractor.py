"""Step 2: ask the AI to read the document and fill in the form (Extraction).
"""
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import ValidationError

from .schema import Extraction

load_dotenv()

SYSTEM_PROMPT = """You read supplier quotations for a garment company and copy facts into JSON.

Strict rules:
- Copy values exactly as written. Do NOT calculate, convert, round or fix anything.
  (If delivery says "4 weeks", return number 4 and unit "weeks". If a total looks wrong, copy it anyway.)
- For every value, put the exact words from the document in "quote" (copy-paste, same spelling and numbers).
- If something is not in the document, use null for value and quote. Never guess.
- Numbers: plain numbers without commas or currency (12,000 -> 12000).
- payment.advance_percent: the % paid with the purchase order (0 if it says no advance).
- payment.balance_days_min / max: days allowed to pay the rest. "within 45 days" -> min 45, max 45.
  "30 to 90 days" -> min 30, max 90.
- payment.counted_from: is that period counted from "delivery" or "purchase order"? Otherwise "unclear".
- payment.is_clear: false if the payment text is repeated, contradicts itself, or depends on a later agreement.
- penalty.present: is there a late-delivery penalty clause? basis_is_order_value: true only if it says "of order value".
- prices_include_vat: true if the document says prices or total already include VAT/taxes.

Return ONLY a JSON object with exactly this structure:
{
  "supplier_name": {"value": str, "quote": str},
  "quotation_no": {"value": str, "quote": str},
  "quote_date": {"value": str, "quote": str},
  "pr_reference": {"value": str, "quote": str},
  "items": [{"item_code": str, "description": str, "quantity": num, "unit": str,
             "unit_price": num, "amount": num, "quote": "the whole table row"}],
  "subtotal": {"value": num, "quote": str},
  "vat_rate_percent": {"value": num, "quote": str},
  "vat_amount": {"value": num, "quote": str},
  "total": {"value": num, "quote": str},
  "prices_include_vat": bool,
  "tin": {"value": str, "quote": str},
  "bin": {"value": str, "quote": str},
  "payment": {"advance_percent": num, "balance_days_min": num, "balance_days_max": num,
              "counted_from": "delivery" | "purchase order" | "unclear", "is_clear": bool, "quote": str},
  "delivery": {"number": num, "unit": "days" | "weeks" | "months", "quote": str},
  "penalty": {"present": bool, "percent": num, "per": "week" | "day" | "month" | "other",
              "basis_is_order_value": bool, "quote": str},
  "validity_days": {"value": num, "quote": str}
}"""


class ExtractionError(Exception):
    pass


def llm_extract(text: str, max_attempts: int = 3) -> Extraction:
    """Call the AI. If the answer is not valid JSON in our shape, tell it the error and try once more."""
    from openai import OpenAI  # imported here so tests do not need it

    api_key = os.getenv("LLM_API_KEY")
    if not api_key:
        raise ExtractionError("No LLM_API_KEY set. Copy .env.example to .env and add a key.")
    client = OpenAI(
        api_key=api_key,
        base_url=os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1"),
        timeout=60,
    )
    model = os.getenv("LLM_MODEL", "openai/gpt-oss-120b")

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Document:\n<<<\n{text}\n>>>"},
    ]
    last_error = ""
    json_mode = {"response_format": {"type": "json_object"}}
    for _ in range(max_attempts):
        try:
            response = client.chat.completions.create(model=model, messages=messages, temperature=0, **json_mode)
        except Exception as exc:  # network, rate limit, bad key...
            last_error = f"AI service error: {exc}"
            if "response_format" in str(exc) and json_mode:
                json_mode = {}  # this provider/model has no JSON mode; the prompt still asks for JSON
            continue
        raw = (response.choices[0].message.content or "").strip()
        if raw.startswith("```"):  # some models wrap JSON in a code block
            raw = raw.strip("`").removeprefix("json").strip()
        try:
            return Extraction.model_validate(json.loads(raw))
        except (json.JSONDecodeError, ValidationError) as exc:
            last_error = f"AI returned data in the wrong shape: {exc}"
            messages += [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": f"That was not valid. Error: {exc}. Return only the corrected JSON."},
            ]
    raise ExtractionError(last_error)


def golden_extract(pdf_path: str | Path) -> Extraction:

    golden = Path(__file__).parent.parent / "tests" / "golden" / (Path(pdf_path).stem + ".json")
    if not golden.exists():
        raise ExtractionError(f"No hand-checked file for {Path(pdf_path).name} (offline mode only covers the 10 samples).")
    return Extraction.model_validate_json(golden.read_text())
