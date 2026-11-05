"""Run with: pytest -q"""
import csv
import uuid
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from checker import rules
from checker.extractor import ExtractionError, golden_extract
from checker.graph import build_graph, check_document
from checker.pdf_reader import read_pdf
from checker.schema import APPROVE, NEEDS_PERSON, REJECT
from checker.verify import verify_evidence

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"
EXPECTED = {r["pack"]: r["expected_decision"] for r in csv.DictReader(open(DATA / "expected_results.csv"))}


def run_with(extraction_fn, pdf="supplier-pack-01.pdf"):
    graph = build_graph(lambda text, path: extraction_fn(path))
    return graph.invoke({"pdf_path": str(DATA / pdf), "ask_human": False, "log": []})


# ---- 1. The rules give the right answer on all 10 samples (with correct reading)
@pytest.mark.parametrize("pack", sorted(EXPECTED))
def test_rules_on_hand_checked_extraction(pack):
    state = check_document(DATA / f"{pack}.pdf", mode="offline")
    assert state["decision"] == EXPECTED[pack]


# ---- 2. Every hand-checked quote is really in its PDF (the evidence checker accepts true quotes)
@pytest.mark.parametrize("pack", sorted(EXPECTED))
def test_true_quotes_pass_evidence_check(pack):
    pdf = DATA / f"{pack}.pdf"
    problems, unverified, _ = verify_evidence(golden_extract(pdf), read_pdf(pdf))
    assert problems == [] and unverified == set()


# ---- 3. "Never guess" safety behaviour
def test_invented_quote_is_caught_and_not_rejected():
    """The AI invents a 40% advance on a good document. We must not reject on made-up evidence."""
    def fake(path):
        ex = golden_extract(path)
        ex.payment.advance_percent = 40
        ex.payment.quote = "40% advance payable with the purchase order."  # not in pack 02
        return ex
    state = run_with(fake, "supplier-pack-02.pdf")
    assert state["decision"] == NEEDS_PERSON
    assert any(f.check == "Evidence check" for f in state["reasons"])


def test_number_not_in_quote_is_caught():
    def fake(path):
        ex = golden_extract(path)
        ex.items[0].unit_price = 450.0  # real quote row still says 472.00
        return ex
    state = run_with(fake, "supplier-pack-01.pdf")
    assert state["decision"] == NEEDS_PERSON


def test_ai_says_tin_missing_but_document_has_it():
    def fake(path):
        ex = golden_extract(path)
        ex.tin.value = ex.tin.quote = None
        return ex
    state = run_with(fake, "supplier-pack-01.pdf")
    assert state["decision"] == NEEDS_PERSON  # not Reject


def test_ai_says_penalty_missing_but_document_has_it():
    def fake(path):
        ex = golden_extract(path)
        ex.penalty.present = False
        return ex
    assert run_with(fake, "supplier-pack-02.pdf")["decision"] == NEEDS_PERSON


def test_ai_failure_goes_to_a_person():
    def broken(path):
        raise ExtractionError("AI service error: timeout")
    state = run_with(broken)
    assert state["decision"] == NEEDS_PERSON
    assert "timeout" in state["reasons"][0].reason


def test_unreadable_pdf_goes_to_a_person(tmp_path):
    from pypdf import PdfWriter
    blank = tmp_path / "scanned.pdf"
    w = PdfWriter()
    w.add_blank_page(595, 842)
    w.write(blank)
    graph = build_graph(lambda t, p: pytest.fail("should not reach extraction"))
    state = graph.invoke({"pdf_path": str(blank), "ask_human": False, "log": []})
    assert state["decision"] == NEEDS_PERSON


# ---- 4. Rule boundaries
@pytest.mark.parametrize("price,expected", [(480.0, APPROVE), (494.40, NEEDS_PERSON), (494.41, REJECT)])
def test_price_boundaries(price, expected):
    pr = rules.load_purchase_request(DATA / "purchase-request.csv")
    ex = golden_extract(DATA / "supplier-pack-01.pdf")
    ex.items[0].unit_price = price
    price_finding = [f for f in rules.compare_with_request(ex, pr) if f.check == "Price"][0]
    assert price_finding.outcome == expected


@pytest.mark.parametrize("days,expected", [(30, APPROVE), (31, NEEDS_PERSON), (45, NEEDS_PERSON), (46, REJECT)])
def test_delivery_boundaries(days, expected):
    ex = golden_extract(DATA / "supplier-pack-01.pdf")
    ex.delivery.number = days
    f = [f for f in rules.check_contract_rules(ex) if f.check == "Delivery"][0]
    assert f.outcome == expected


# ---- 5. Human in the loop: the graph pauses and resumes with the person's answer
def test_pauses_for_a_person_and_resumes():
    graph = build_graph(lambda t, p: golden_extract(p), checkpointer=MemorySaver())
    cfg = {"configurable": {"thread_id": str(uuid.uuid4())}}
    graph.invoke({"pdf_path": str(DATA / "supplier-pack-04.pdf"), "ask_human": True, "log": []}, cfg)
    assert graph.get_state(cfg).next == ("human_review",)  # paused, waiting
    final = graph.invoke(Command(resume={"decision": APPROVE, "note": "Price agreed by phone"}), cfg)
    assert final["decision"] == NEEDS_PERSON and final["human_decision"] == APPROVE
