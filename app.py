"""Web demo. Run: streamlit run app.py"""
import csv
import os
import tempfile
import time
import uuid
from pathlib import Path

import streamlit as st
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from checker.graph import build_graph, get_extractor
from checker.schema import APPROVE, NEEDS_PERSON, REJECT

ROOT = Path(__file__).parent
DATA = ROOT / "data"
EXPECTED = {r["pack"]: r for r in csv.DictReader(open(DATA / "expected_results.csv"))}
SAMPLES = sorted(p.name for p in DATA.glob("supplier-pack-*.pdf"))
ICON = {APPROVE: "✅", NEEDS_PERSON: "🟡", REJECT: "❌"}
COLOR = {APPROVE: "green", NEEDS_PERSON: "orange", REJECT: "red"}

st.set_page_config(page_title="Supplier Document Checker", page_icon="📄", layout="wide")

# API key: 
try:
    for k in ["LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL"]:
        if k in st.secrets and not os.getenv(k):
            os.environ[k] = st.secrets[k]
except Exception:
    pass
has_key = bool(os.getenv("LLM_API_KEY"))

# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.header("Settings")
    mode_label = st.radio(
        "Who reads the document?",
        ["AI model", "Hand-checked answers (no AI)"],
        index=0 if has_key else 1,
        help="'Hand-checked answers' skips the AI and uses readings I typed in by hand. "
             "It shows the rules working, and is how the tests run.",
    )
    mode = "ai" if mode_label == "AI model" else "offline"
    if mode == "ai":
        if has_key:
            st.success(f"AI: {os.getenv('LLM_MODEL', 'openai/gpt-oss-120b')}")
        else:
            st.error("No API key set. Add LLM_API_KEY to .env (see README).")
    st.divider()
    st.caption("Purchase request: PR-2026-114 · Rules: data/company-rules.md")

st.title("📄 Supplier Document Checker")
st.write("Checks supplier quotations against the purchase request and company rules, step by step. "
         "The AI only **reads** the document; plain code does the maths and the rules. "
         "When the system is not sure, it **stops and asks a person**.")

tab_one, tab_all, tab_how = st.tabs(["Check one document", "Check all 10 samples", "How it works"])


def show_result(state: dict):
    decision = state["decision"]
    st.markdown(f"### {ICON[decision]} :{COLOR[decision]}[{decision}]")
    if state.get("human_decision"):
        st.info(f"👤 A person decided: **{state['human_decision']}**" +
                (f" — “{state['human_note']}”" if state.get("human_note") else ""))

    if decision != APPROVE:
        st.markdown("**Why:**")
        for r in state["reasons"]:
            st.markdown(f"- {r.reason}")
            if r.quote:
                st.caption(f"   Document says: “{r.quote}”")

    with st.expander("All checks", expanded=decision == APPROVE):
        for f in state.get("findings", []):
            st.markdown(f"{ICON[f.outcome]} **{f.check}** — {f.reason}")
            if f.quote:
                st.caption(f"Document says: “{f.quote}”")
    with st.expander("Steps the system ran"):
        for line in state.get("log", []):
            st.text(line)
    if state.get("extraction") and mode == "ai":
        with st.expander("What the AI read from the document (with quotes)"):
            st.json(state["extraction"].model_dump(), expanded=False)


# ------------------------------------------------------------------ tab 1
with tab_one:
    left, right = st.columns([1, 2])
    with left:
        if mode == "ai":
            source = st.radio("Document", ["Sample pack", "Upload a PDF"], horizontal=True)
        else:
            source = "Sample pack"
            st.caption("Offline mode only works on the 10 sample packs.")
        pdf_path = None
        if source == "Sample pack":
            name = st.selectbox("Choose a sample", SAMPLES)
            pdf_path = str(DATA / name)
            st.caption(f"Answer key: **{EXPECTED[Path(name).stem]['expected_decision']}**")
        else:
            up = st.file_uploader("PDF quotation", type="pdf")
            if up:
                tmp = Path(tempfile.gettempdir()) / f"upload-{uuid.uuid4().hex}.pdf"
                tmp.write_bytes(up.getvalue())
                pdf_path = str(tmp)
        run = st.button("Check document", type="primary", disabled=pdf_path is None)

    with right:
        if run:
            graph = build_graph(get_extractor(mode), checkpointer=MemorySaver())
            cfg = {"configurable": {"thread_id": uuid.uuid4().hex}}
            with st.spinner("Checking..."):
                state = graph.invoke({"pdf_path": pdf_path, "ask_human": True, "log": []}, cfg)
            st.session_state.update(graph=graph, cfg=cfg, run_mode=mode)

        if "graph" in st.session_state:
            graph, cfg = st.session_state.graph, st.session_state.cfg
            snap = graph.get_state(cfg)
            state = snap.values
            show_result(state)

            if snap.next == ("human_review",):  
                st.divider()
                st.markdown("#### 👤 The system is not sure. Please decide.")
                note = st.text_input("Note (optional)", key=f"note-{cfg['configurable']['thread_id']}")
                c1, c2 = st.columns(2)
                for col, choice in [(c1, APPROVE), (c2, REJECT)]:
                    if col.button(f"{ICON[choice]} {choice}", use_container_width=True):
                        graph.invoke(Command(resume={"decision": choice, "note": note}), cfg)
                        st.rerun()

# ------------------------------------------------------------------ tab 2
with tab_all:

    if st.button("Run all 10", type="primary"):
        graph = build_graph(get_extractor(mode))
        rows, correct, bar = [], 0, st.progress(0.0)
        for i, name in enumerate(SAMPLES):
            t0 = time.time()
            s = graph.invoke({"pdf_path": str(DATA / name), "ask_human": False, "log": []})
            exp = EXPECTED[Path(name).stem]["expected_decision"]
            correct += s["decision"] == exp
            rows.append({
                "Pack": Path(name).stem.replace("supplier-pack-", "Pack "),
                "Supplier": s["extraction"].supplier_name.value if s.get("extraction") else "—",
                "Expected": exp,
                "System": f"{ICON[s['decision']]} {s['decision']}",
                "Right?": "✓" if s["decision"] == exp else "✗",
                "Main reason": "; ".join(r.reason for r in s["reasons"][:2]) if s["decision"] != APPROVE else "All checks passed",
                "Seconds": round(time.time() - t0, 1),
            })
            bar.progress((i + 1) / len(SAMPLES))
        st.metric("Correct", f"{correct} / {len(SAMPLES)}")
        st.dataframe(rows, use_container_width=True, hide_index=True)

# ------------------------------------------------------------------ tab 3
with tab_how:
    st.markdown("""
**Six fixed steps, always in the same order** (built with LangGraph; no free-running agent):

1. **Read the PDF** into text. If it has no text (e.g. a scan), stop and send it to a person.
2. **AI reads the document** and fills in a fixed form: supplier, items, quantities, prices, VAT, TIN/BIN,
   payment, delivery, penalty, validity. For **every value it must copy the exact words** it read it from.
3. **Evidence check (no AI).** Is each quote really in the document? Is the number really in the quote?
   If the AI says the TIN or penalty clause is missing, It will search the document to make sure.
4. **Compare with the purchase request (no AI):** quantity and unit price.
5. **Apply the company rules (no AI):** advance, payment days, penalty, TIN/BIN, delivery days, VAT, totals, validity.
6. **Decide:** any Reject rule → **Reject**; otherwise any review rule → **Needs a person to check**;
   otherwise **Approve**. It only reject on confirmed evidence: if the evidence for a rejection
   could not be confirmed, it goes to a person instead.

→ **Needs a person** pauses the pipeline and waits for a human decision.
""")
    st.graphviz_chart("""
digraph { rankdir=LR; node [shape=box, style="rounded,filled", fillcolor="#f4f4f4", fontname="Helvetica"];
 read [label="1. Read PDF"]; ai [label="2. AI reads\\n(+ quotes)", fillcolor="#dbeafe"];
 ev [label="3. Evidence\\ncheck"]; pr [label="4. Compare with\\npurchase request"];
 ru [label="5. Company\\nrules"]; de [label="6. Decide"];
 hu [label="👤 Person\\nreviews", fillcolor="#fef3c7"]; done [label="Approve /\\nReject", fillcolor="#dcfce7"];
 read -> ai -> ev -> pr -> ru -> de; de -> done [label="sure"]; de -> hu [label="not sure"];
 read -> hu [label="error", style=dashed]; ai -> hu [label="error", style=dashed]; }
""")
