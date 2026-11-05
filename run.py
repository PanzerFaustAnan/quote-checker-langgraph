"""Check all supplier packs and score the results.

    python run.py              # use the AI
    python run.py --offline    # use the hand-checked readings instead of the AI (no key needed)
"""
import argparse
import csv
import json
import time
from pathlib import Path

from checker.extractor import golden_extract
from checker.graph import check_document
from checker.schema import Extraction

ROOT = Path(__file__).parent
DATA = ROOT / "data"
RESULTS = ROOT / "results"


def flatten(ex: Extraction) -> dict:
    """All values (not quotes) as {field: value}, for comparing the AI with the answer key."""
    d = ex.model_dump()
    flat = {}

    def walk(prefix, obj):
        if isinstance(obj, dict):
            if set(obj) == {"value", "quote"}:
                flat[prefix] = obj["value"]
                return
            for k, v in obj.items():
                if k != "quote":
                    walk(f"{prefix}.{k}" if prefix else k, v)
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                walk(f"{prefix}[{i}]", v)
        else:
            flat[prefix] = obj
    walk("", d)
    return flat


def same(a, b) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        return abs(a - b) < 0.01
    if isinstance(a, str) and isinstance(b, str):
        return " ".join(a.lower().split()) == " ".join(b.lower().split())
    return a == b


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="use hand-checked readings instead of the AI")
    args = ap.parse_args()
    mode = "offline" if args.offline else "ai"

    expected = {r["pack"]: r for r in csv.DictReader(open(DATA / "expected_results.csv"))}
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "ai_extractions").mkdir(exist_ok=True)

    rows, correct, field_total, field_right, wrong_fields = [], 0, 0, 0, []
    for pdf in sorted(DATA.glob("supplier-pack-*.pdf")):
        start = time.time()
        state = check_document(pdf, mode=mode)
        seconds = time.time() - start
        exp = expected[pdf.stem]["expected_decision"]
        ok = state["decision"] == exp
        correct += ok
        reasons = [r.reason for r in state["reasons"] if r.outcome == state["decision"]]

        if mode == "ai" and state.get("extraction"):
            ex = state["extraction"]
            (RESULTS / "ai_extractions" / f"{pdf.stem}.json").write_text(ex.model_dump_json(indent=2))
            truth, got = flatten(golden_extract(pdf)), flatten(ex)
            for k, v in truth.items():
                field_total += 1
                if same(got.get(k), v):
                    field_right += 1
                else:
                    wrong_fields.append(f"{pdf.stem} {k}: AI={got.get(k)!r} correct={v!r}")

        rows.append({"pack": pdf.stem, "expected": exp, "system": state["decision"], "correct": ok,
                     "seconds": round(seconds, 1), "reasons": reasons, "log": state.get("log", [])})
        print(f"{'✓' if ok else '✗'} {pdf.stem}  expected: {exp:<24} system: {state['decision']:<24} ({seconds:.1f}s)")
        for r in reasons:
            print(f"      - {r}")

    print(f"\nScore: {correct} / {len(rows)} correct  (mode: {mode})")
    summary = {"mode": mode, "correct": correct, "total": len(rows), "results": rows}
    if field_total:
        print(f"AI reading accuracy: {field_right} / {field_total} fields match the hand-checked answers "
              f"({field_right / field_total:.1%})")
        for w in wrong_fields:
            print(f"      - {w}")
        summary |= {"fields_right": field_right, "fields_total": field_total, "wrong_fields": wrong_fields}
    (RESULTS / f"results-{mode}.json").write_text(json.dumps(summary, indent=2, default=str))
    print(f"Saved results/results-{mode}.json")


if __name__ == "__main__":
    main()
