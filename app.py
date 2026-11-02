"""
app.py -- Streamlit UI for the integrated triage agent (Clarifier + Resolver).

    streamlit run app.py

You play the customer. The sidebar shows what each agent decided: the Clarifier's status and
hypotheses, the signature handed to the Resolver, the evidence gate, and any escalation payload.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import streamlit as st

from triage.agent import DEFAULT_KB, TriageAgent
from triage.config import PROJECT_ROOT
from triage.ocr import extract_text_from_image, extract_error_context

KBS = {"Docker KB (10k chunks)": DEFAULT_KB, "Mini fixture KB (12 chunks)": PROJECT_ROOT / "fixtures" / "kb_mini.jsonl"}
MODES = {"Offline (heuristics + FakeLLM, free)": "offline", "LLM from .env (LLM_PROVIDER)": "provider"}

st.set_page_config(page_title="Docker Support Triage", page_icon="🐳", layout="wide")


@st.cache_resource(show_spinner="Loading agent and knowledge base...")
def get_agent(mode: str, kb: str) -> TriageAgent:
    return TriageAgent(llm_mode=mode, kb_path=kb)


with st.sidebar:
    st.header("Settings")
    mode = MODES[st.radio("Models", list(MODES))]
    kb = str(KBS[st.radio("Knowledge base", list(KBS))])
    if st.button("New ticket", use_container_width=True) or st.session_state.get("cfg") != (mode, kb):
        st.session_state.update(ticket=None, cfg=(mode, kb))

try:
    agent = get_agent(mode, kb)
except Exception as e:  # noqa: BLE001 -- e.g. missing API key for the LLM mode
    st.error(f"Could not start the agent: {e}")
    st.stop()

tid = st.session_state.get("ticket")
state = agent.state(tid) if tid else {}
waiting = state.get("waiting_for")
closed = bool(tid) and not waiting

st.title("🐳 Docker Support Triage")
st.caption(f"Ticket `{tid}`" if tid else "Describe a Docker problem to open a ticket.")

for turn in state.get("transcript") or []:
    with st.chat_message("user" if turn["role"] == "user" else "assistant"):
        st.markdown(turn["content"].replace("\n", "  \n"))
        # Show attached image if present
        if turn.get("image_path") and Path(turn["image_path"]).exists():
            st.image(turn["image_path"], caption="Attached screenshot", width=400)

if closed:
    outcome = state.get("outcome", "?")
    (st.success if outcome == "resolved" else st.warning)(
        f"Ticket closed: **{outcome}**" + (f" ({state['escalation_reason']})" if state.get("escalation_reason") else "")
        + ". Use **New ticket** in the sidebar to start again.")

# ---- Input area: text + attachment ----
col_input, col_attach = st.columns([4, 1])

with col_attach:
    uploaded = st.file_uploader(
        "📎 Screenshot",
        type=["png", "jpg", "jpeg", "bmp", "tiff", "webp"],
        disabled=closed,
        label_visibility="collapsed",
        help="Attach a screenshot of the error",
    )

    if uploaded and "last_upload_name" not in st.session_state:
        st.session_state["last_upload_name"] = None

    # Show preview of uploaded image
    if uploaded:
        st.image(uploaded, caption="Preview", width=150)

prompt = st.chat_input("Ticket closed" if closed else "Type your message...", disabled=closed)

# Process submission (text and/or image)
if prompt or (uploaded and st.session_state.get("last_upload_name") != uploaded.name):
    combined_message = prompt or ""
    image_path = None
    ocr_context = ""

    # Process uploaded image
    if uploaded:
        st.session_state["last_upload_name"] = uploaded.name
        # Save uploaded file
        upload_dir = PROJECT_ROOT / "uploads"
        upload_dir.mkdir(exist_ok=True)
        image_path = str(upload_dir / uploaded.name)
        with open(image_path, "wb") as f:
            f.write(uploaded.getvalue())

        # Extract text via OCR
        with st.spinner("Extracting text from screenshot..."):
            extracted_text = extract_text_from_image(uploaded.getvalue())

        if extracted_text:
            # Parse for error context
            error_ctx = extract_error_context(extracted_text)

            # Build OCR context string
            ocr_parts = [f"[Screenshot attached: {uploaded.name}]"]
            ocr_parts.append(f"[Extracted text from screenshot:\n{extracted_text}\n]")

            if error_ctx["error_messages"]:
                ocr_parts.append(f"[Detected errors: {'; '.join(error_ctx['error_messages'][:3])}]")
            if error_ctx["exit_codes"]:
                ocr_parts.append(f"[Exit codes: {', '.join(error_ctx['exit_codes'])}]")

            ocr_context = "\n".join(ocr_parts)
        else:
            ocr_context = f"[Screenshot attached: {uploaded.name}, but no text could be extracted. Please describe the issue you see in the screenshot.]"

    # Combine user text + OCR extracted text
    if combined_message and ocr_context:
        full_message = f"{combined_message}\n\n{ocr_context}"
    elif ocr_context:
        full_message = ocr_context
    else:
        full_message = combined_message

    if full_message:
        try:
            with st.spinner("Agent is working..."):
                if tid:
                    agent.reply(tid, full_message)
                else:
                    st.session_state["ticket"] = agent.start(full_message)
        except Exception as e:  # noqa: BLE001 -- surface LLM/provider failures instead of a blank page
            st.error(f"Agent error: {e}")
        st.rerun()

with st.sidebar:
    if tid:
        st.header("Agent trace")
        st.metric("Now", {"clarifier_question": "Clarifier asking", "resolver_message": "Resolver awaiting reply"}
                  .get((waiting or {}).get("type"), "Closed"))
        c1, c2 = st.columns(2)
        c1.metric("Outcome", state.get("outcome") or "in_progress")
        c2.metric("Confidence", f"{state['confidence']:.2f}" if state.get("confidence") is not None else "-")
        st.write(f"**Clarifier:** {state.get('clarifier_status')} ({state.get('clarifier_reason')})")
        st.write(f"**Gate:** {state.get('gate_decision') or '-'} · **Tier:** {state.get('tier') or '-'} · "
                 f"**Cache:** {state.get('cache_status') or '-'}")
        meta = state.get("clarifier_meta") or {}
        if meta.get("hypotheses"):
            with st.expander("Clarifier hypotheses"):
                for h in meta["hypotheses"]:
                    st.write(f"{h['weight']:.2f} · {h['label']}")
        if state.get("signature"):
            with st.expander("Signature handed to Resolver"):
                st.json(state["signature"])
        if state.get("evidence"):
            with st.expander(f"Evidence ({len(state['evidence'])})"):
                for e in state["evidence"]:
                    st.markdown(f"**{e['evidence_id']}** ({e['tier']}, {e['rerank_score']:.2f}) {e.get('url') or e['doc_id']}")
                    st.caption(e["text"][:300])
        if state.get("gate_detail"):
            with st.expander("Gate detail"):
                st.json(state["gate_detail"])
        if state.get("escalation_payload"):
            with st.expander("Escalation payload", expanded=True):
                st.markdown(state["escalation_payload"]["summary_md"])
                st.download_button("Download JSON", json.dumps(state["escalation_payload"], indent=2),
                                   f"{tid}_escalation.json", "application/json")

        # OCR info in sidebar
        if state.get("transcript"):
            ocr_turns = [t for t in state["transcript"] if "[Extracted text from screenshot:" in t.get("content", "")]
            if ocr_turns:
                with st.expander("📷 Screenshot OCR Results"):
                    for t in ocr_turns:
                        content = t["content"]
                        # Extract just the OCR portion
                        start = content.find("[Extracted text from screenshot:")
                        end = content.find("]", start)
                        if start >= 0 and end >= 0:
                            st.text(content[start:end + 1])
