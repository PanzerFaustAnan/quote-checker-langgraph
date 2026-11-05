"""The fixed pipeline, built with LangGraph.

    read_pdf -> extract -> verify_evidence -> compare_with_request -> check_rules -> decide
                                                                                  |
                                              "Needs a person to check" ---------> human_review

The AI is used in exactly one step (extract). Every other step is plain Python.
If any step fails, the document goes straight to human_review. Nothing is guessed.
"""
from pathlib import Path
from typing import Callable, Optional, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from . import rules
from .extractor import ExtractionError, golden_extract, llm_extract
from .pdf_reader import PDFReadError, read_pdf
from .schema import APPROVE, NEEDS_PERSON, REJECT, Extraction, Finding
from .verify import verify_evidence

ROOT = Path(__file__).parent.parent
DEFAULT_PR = ROOT / "data" / "purchase-request.csv"


class State(TypedDict, total=False):
    pdf_path: str
    pr_path: str
    ask_human: bool          
    text: str
    extraction: Extraction
    unverified: list[str]
    fields_checked: int
    findings: list[Finding]
    decision: str
    reasons: list[Finding]
    error: Optional[str]
    human_decision: Optional[str]
    human_note: Optional[str]
    log: list[str]


def _log(state: State, msg: str) -> list[str]:
    return state.get("log", []) + [msg]


def build_graph(extract_fn: Callable[[str, str], Extraction], checkpointer=None):
    """extract_fn(text, pdf_path) -> Extraction. Pass the AI or the offline reader."""

    def node_read_pdf(state: State) -> State:
        try:
            text = read_pdf(state["pdf_path"])
            return {"text": text, "log": _log(state, f"1. Read PDF: {len(text)} characters.")}
        except PDFReadError as exc:
            return {"error": str(exc), "log": _log(state, f"1. Read PDF FAILED: {exc}")}

    def node_extract(state: State) -> State:
        try:
            ex = extract_fn(state["text"], state["pdf_path"])
            return {"extraction": ex, "log": _log(state, f"2. Extracted {len(ex.items)} item(s) from "
                                                         f"{ex.supplier_name.value or 'unknown supplier'}.")}
        except ExtractionError as exc:
            return {"error": str(exc), "log": _log(state, f"2. Extraction FAILED: {exc}")}

    def node_verify(state: State) -> State:
        problems, unverified, checked = verify_evidence(state["extraction"], state["text"])
        return {"findings": problems, "unverified": sorted(unverified), "fields_checked": checked,
                "log": _log(state, f"3. Evidence check: {checked} values checked, {len(problems)} problem(s).")}

    def node_compare(state: State) -> State:
        pr = rules.load_purchase_request(state.get("pr_path") or DEFAULT_PR)
        found = rules.compare_with_request(state["extraction"], pr)
        return {"findings": state["findings"] + found,
                "log": _log(state, f"4. Compared with purchase request: {len(found)} check(s).")}

    def node_rules(state: State) -> State:
        found = rules.check_contract_rules(state["extraction"])
        return {"findings": state["findings"] + found,
                "log": _log(state, f"5. Applied company rules: {len(found)} check(s).")}

    def node_decide(state: State) -> State:
        decision, final = rules.decide(state["findings"], set(state.get("unverified", [])))
        reasons = [f for f in final if f.outcome == decision] if decision != APPROVE else final
        return {"decision": decision, "findings": final, "reasons": reasons,
                "log": _log(state, f"6. Decision: {decision}.")}

    def node_human_review(state: State) -> State:
        if state.get("error"):
            update: State = {"decision": NEEDS_PERSON, "reasons": [Finding(
                check="System", outcome=NEEDS_PERSON, reason=f"The system could not finish: {state['error']}")]}
        else:
            update = {}
        if not state.get("ask_human"):
            return {**update, "log": _log(state, "7. Sent to the review queue for a person.")}
        # Pause here. The app shows the evidence and resumes with the person's answer.
        answer = interrupt({"question": "Please decide: Approve or Reject?",
                            "reasons": [r.reason for r in (update.get("reasons") or state.get("reasons", []))]})
        return {**update, "human_decision": answer.get("decision"), "human_note": answer.get("note"),
                "log": _log(state, f"7. Person decided: {answer.get('decision')}.")}

    def after(step_ok: str):
        return lambda s: "human_review" if s.get("error") else step_ok

    g = StateGraph(State)
    g.add_node("read_pdf", node_read_pdf)
    g.add_node("extract", node_extract)
    g.add_node("verify_evidence", node_verify)
    g.add_node("compare_with_request", node_compare)
    g.add_node("check_rules", node_rules)
    g.add_node("decide", node_decide)
    g.add_node("human_review", node_human_review)

    g.add_edge(START, "read_pdf")
    g.add_conditional_edges("read_pdf", after("extract"), ["extract", "human_review"])
    g.add_conditional_edges("extract", after("verify_evidence"), ["verify_evidence", "human_review"])
    g.add_edge("verify_evidence", "compare_with_request")
    g.add_edge("compare_with_request", "check_rules")
    g.add_edge("check_rules", "decide")
    g.add_conditional_edges("decide", lambda s: "human_review" if s["decision"] == NEEDS_PERSON else END,
                            ["human_review", END])
    g.add_edge("human_review", END)
    return g.compile(checkpointer=checkpointer)


def get_extractor(mode: str) -> Callable[[str, str], Extraction]:
    if mode == "ai":
        return lambda text, path: llm_extract(text)
    if mode == "offline":
        return lambda text, path: golden_extract(path)
    raise ValueError(f"Unknown mode {mode}")


def check_document(pdf_path: str | Path, mode: str = "ai", pr_path: str | Path = DEFAULT_PR) -> State:
    """Run one document through the whole pipeline without pausing (used for batch runs)."""
    graph = build_graph(get_extractor(mode))
    return graph.invoke({"pdf_path": str(pdf_path), "pr_path": str(pr_path), "ask_human": False, "log": []})


__all__ = ["build_graph", "check_document", "get_extractor", "MemorySaver", "APPROVE", "NEEDS_PERSON", "REJECT"]
