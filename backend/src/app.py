"""CashTrace — Financial Control Tower.

A polished operator-facing surface over the existing deterministic reconciliation
engine. The backend remains unchanged: CashTrace reframes reconciliation as
lifecycle verification and investigation rather than a flat match table.

Run: streamlit run src/app_cashtrace.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(__file__))

import agent as ops_agent
from categorize import build_memory_from_golden, categorize_one, load_bank_feed
from model import USING_MOCK
from policy_rag import KnowledgeBaseIndex
from reconcile import load_payouts, reconcile, summarize
from schema import income_statement_section

AUTO_APPROVE = 0.75
DATA_DIR = Path(__file__).resolve().parent.parent / "data"

st.set_page_config(page_title="CashTrace | Financial Control Tower", page_icon="◈", layout="wide")

st.markdown("""
<style>
.block-container {padding-top: 2rem; padding-bottom: 3rem; max-width: 1500px;}
.hero {padding: 1.5rem 1.7rem; border: 1px solid rgba(128,128,128,.25); border-radius: 18px; margin-bottom: 1.2rem; background: linear-gradient(135deg, rgba(120,120,120,.08), rgba(120,120,120,.02));}
.hero h1 {margin: 0 0 .25rem 0; font-size: 2.25rem; letter-spacing: -.04em;}
.hero p {margin: 0; color: #777; font-size: 1rem;}
.section-title {font-size: 1.15rem; font-weight: 700; margin: 1.3rem 0 .55rem;}
.small {font-size: .82rem; color: #777;}
.verdict {padding: .65rem .85rem; border-radius: 10px; border: 1px solid rgba(128,128,128,.25); margin: .35rem 0;}
.metric-card {padding: .9rem 1rem; border: 1px solid rgba(128,128,128,.22); border-radius: 13px; min-height: 105px;}
.metric-label {font-size: .78rem; color: #777; text-transform: uppercase; letter-spacing: .05em;}
.metric-value {font-size: 1.55rem; font-weight: 750; margin-top: .2rem;}
.metric-help {font-size: .76rem; color: #888; margin-top: .15rem;}
hr {margin: 1.1rem 0;}
</style>
""", unsafe_allow_html=True)


def money(x: float | int | None) -> str:
    if x is None:
        return "—"
    return f"${x:,.2f}"


def verdict_for(status: str) -> str:
    return {
        "matched": "VERIFIED",
        "partial_reserve": "PROBABLE",
        "unmatched": "UNRESOLVED",
    }.get(status, "UNRESOLVED")


def materiality(amount: float, expected: float | None) -> tuple[str, float]:
    """Small, explainable prioritisation heuristic; not a financial control."""
    if not expected:
        return ("High" if amount >= 500 else "Medium", 100.0 if amount >= 500 else 60.0)
    rel = amount / max(abs(expected), 1.0)
    score = min(100.0, round((rel * 70) + min(amount / 1000, 1) * 30, 1))
    if amount >= 500 or rel >= .05:
        return "High", score
    if amount >= 100 or rel >= .02:
        return "Medium", score
    return "Low", score


@st.cache_data(show_spinner="Loading financial data…")
def load_reconciliation() -> tuple[pd.DataFrame, dict, pd.DataFrame]:
    matches = reconcile()
    payouts = {p.payout_id: p for p in load_payouts()}
    bank_rows = {r["txn_id"]: r for r in load_bank_feed()}
    rows = []
    for m in matches:
        payout = payouts.get(m.payout_id)
        expected = m.expected_net
        discrepancy = m.discrepancy
        risk = abs(discrepancy or 0)
        sev, score = materiality(risk, expected)
        rows.append({
            "txn_id": m.txn_id,
            "date": bank_rows.get(m.txn_id, {}).get("date", "—"),
            "description": bank_rows.get(m.txn_id, {}).get("description", "—"),
            "deposit": m.deposit_amount,
            "payout_id": m.payout_id or "—",
            "channel": payout.channel if payout else "—",
            "gross": payout.gross if payout else None,
            "fees": payout.fees if payout else None,
            "refunds": payout.refunds if payout else None,
            "expected_net": expected,
            "actual_settlement": m.deposit_amount,
            "variance": discrepancy,
            "status": m.status,
            "verdict": verdict_for(m.status),
            "severity": sev if m.status != "matched" else "None",
            "materiality_score": score if m.status != "matched" else 0,
            "note": m.note,
        })
    df = pd.DataFrame(rows)
    return df, summarize(matches), pd.DataFrame(load_bank_feed())


@st.cache_data(show_spinner="Preparing categorization evidence…")
def categorize_all() -> pd.DataFrame:
    feed = load_bank_feed()
    memory = build_memory_from_golden(holdout_ids=set())
    kb = KnowledgeBaseIndex()
    rows = []
    for r in feed:
        res = categorize_one(r["description"], memory=memory, kb=kb)
        pb = res.get("policy_basis")
        rows.append({
            "txn_id": r["txn_id"], "date": r["date"], "description": r["description"],
            "amount": r["amount"], "category": res["category"],
            "confidence": round(res["confidence"], 2),
            "section": income_statement_section(res["category"]),
            "auto_post": res["confidence"] >= AUTO_APPROVE and res["category"] != "Needs Review",
            "cited_rule": f'{pb["doc_id"]}: {pb["title"]}' if pb else "—",
            "rationale": res["rationale"],
        })
    return pd.DataFrame(rows)


def metric_card(label: str, value: str, help_text: str = "") -> None:
    st.markdown(
        f'<div class="metric-card"><div class="metric-label">{label}</div>'
        f'<div class="metric-value">{value}</div><div class="metric-help">{help_text}</div></div>',
        unsafe_allow_html=True,
    )


rec_df, rec_summary, bank_df = load_reconciliation()
cat_df = categorize_all()

processed_amount = float(rec_df["deposit"].sum())
exceptions = rec_df[rec_df["status"] != "matched"].copy()
verified_count = int((rec_df["verdict"] == "VERIFIED").sum())
verification_rate = verified_count / len(rec_df) if len(rec_df) else 0
amount_at_risk = float(exceptions["variance"].abs().sum())

st.markdown(
    '<div class="hero"><h1>◈ CashTrace</h1>'
    '<p><b>Financial Control Tower</b> · Trace every rupee. Verify what can be proven. '
    'Investigate what doesn’t. Prioritize what matters.</p></div>',
    unsafe_allow_html=True,
)

mode = "Offline mock model" if USING_MOCK else os.getenv("APP_LLM_MODEL", "LLM")
st.caption(f"{mode} · AI investigates; deterministic code verifies. · {len(rec_df)} settlement records in the current batch")

tabs = st.tabs(["Overview", "Transaction Explorer", "Exception Center", "Evaluation", "Audit Trail", "Ask Agent"])

with tabs[0]:
    st.markdown('<div class="section-title">Where did the money go?</div>', unsafe_allow_html=True)
    c = st.columns(4)
    with c[0]: metric_card("Processed amount", money(processed_amount), f"Across {len(rec_df)} channel deposits")
    with c[1]: metric_card("Verified", f"{verification_rate:.1%}", f"{verified_count} of {len(rec_df)} deterministic matches")
    with c[2]: metric_card("Exceptions", str(len(exceptions)), "Require explanation or review")
    with c[3]: metric_card("Amount at risk", money(amount_at_risk), "Absolute value of unresolved / discrepant variance")

    st.markdown('<div class="section-title">Money flow</div>', unsafe_allow_html=True)
    flow = st.columns(3)
    with flow[0]: metric_card("Orders / sales", money(float(rec_df["gross"].sum())), "Gross value represented by matched payouts")
    with flow[1]: metric_card("Expected settlements", money(float(rec_df["expected_net"].dropna().sum())), "After fees and refunds")
    with flow[2]: metric_card("Actual deposits", money(processed_amount), "What reached the bank feed")

    st.markdown('<div class="section-title">Exceptions by severity</div>', unsafe_allow_html=True)
    if exceptions.empty:
        st.success("No exceptions detected in this batch.")
    else:
        sev = exceptions.groupby("severity").agg(count=("txn_id", "count"), amount=("variance", lambda s: s.abs().sum())).reindex(["High", "Medium", "Low"]).fillna(0).reset_index()
        st.dataframe(sev.rename(columns={"severity":"Severity", "count":"Exceptions", "amount":"Amount at risk"}), use_container_width=True, hide_index=True)

    st.info("CashTrace does not treat every mismatch as fraud or failure. A mismatch can be explained, probable, or genuinely unresolved; the operator sees the difference.")

with tabs[1]:
    st.markdown('<div class="section-title">Transaction Explorer</div>', unsafe_allow_html=True)
    ids = rec_df["txn_id"].tolist()
    selected = st.selectbox("Select a settlement lifecycle", ids, index=0 if ids else None)
    row = rec_df[rec_df["txn_id"] == selected].iloc[0] if selected else None
    if row is not None:
        st.caption(f"{row['date']} · {row['channel']} · {row['description']}")
        cols = st.columns(4)
        with cols[0]: metric_card("Gross", money(row["gross"]))
        with cols[1]: metric_card("Fees", money(row["fees"]))
        with cols[2]: metric_card("Refunds", money(row["refunds"]))
        with cols[3]: metric_card("Expected net", money(row["expected_net"]))

        st.markdown("**Lifecycle**")
        lifecycle = pd.DataFrame([
            ["01", "Order / sales value", money(row["gross"]), "Source payout"],
            ["02", "Processing fees", money(row["fees"]), "Source payout"],
            ["03", "Refunds / adjustments", money(row["refunds"]), "Source payout"],
            ["04", "Expected settlement", money(row["expected_net"]), "Deterministic calculation"],
            ["05", "Actual bank deposit", money(row["actual_settlement"]), "Bank feed"],
            ["06", "Variance", money(row["variance"]), "Deterministic comparison"],
        ], columns=["Step", "Event", "Amount", "Evidence"])
        st.dataframe(lifecycle, use_container_width=True, hide_index=True)

        verdict = row["verdict"]
        if verdict == "VERIFIED":
            st.success(f"VERDICT · {verdict} — expected net and actual deposit agree within the reconciliation tolerance.")
        elif verdict == "PROBABLE":
            st.warning(f"VERDICT · {verdict} — {row['note']}. This is an explanation hypothesis, not proof.")
        else:
            st.error(f"VERDICT · {verdict} — {row['note']}")

        if row["status"] != "matched":
            st.markdown(f"**Materiality:** {row['severity']} · score {row['materiality_score']}/100")
            st.markdown("**Recommended action:** inspect the source payout, reserve/hold records, refund timing, and bank settlement evidence before closing.")

with tabs[2]:
    st.markdown('<div class="section-title">Exception Center</div>', unsafe_allow_html=True)
    if exceptions.empty:
        st.success("Nothing needs review.")
    else:
        ec = st.columns(3)
        with ec[0]: metric_card("Open exceptions", str(len(exceptions)))
        with ec[1]: metric_card("High materiality", str(int((exceptions["severity"] == "High").sum())))
        with ec[2]: metric_card("Variance", money(amount_at_risk))
        display = exceptions[["txn_id", "date", "channel", "actual_settlement", "expected_net", "variance", "severity", "verdict", "note"]].copy()
        display.columns = ["ID", "Date", "Channel", "Actual", "Expected", "Variance", "Severity", "Verdict", "Investigation note"]
        st.dataframe(display, use_container_width=True, hide_index=True)
        st.caption("Priority is based on amount and relative variance. It is a triage heuristic, not an accounting materiality policy.")

with tabs[3]:
    st.markdown('<div class="section-title">Evaluation · no cherry-picking</div>', unsafe_allow_html=True)
    metrics = {}
    for filename in ["metrics.json", "kb_metrics.json"]:
        path = DATA_DIR / filename
        if path.exists():
            try:
                metrics[filename] = json.loads(path.read_text())
            except Exception:
                pass

    c = st.columns(4)
    with c[0]: metric_card("Batch", str(len(rec_df)), "Settlement records examined")
    with c[1]: metric_card("Verified", f"{verification_rate:.1%}", "Exact deterministic match rate")
    with c[2]: metric_card("Exceptions", str(len(exceptions)), "Not silently accepted")
    with c[3]: metric_card("At risk", money(amount_at_risk), "Discrepant amount currently visible")

    st.markdown("**What the current engine actually found**")
    st.dataframe(pd.DataFrame([
        ["Settlement records examined", len(rec_df)],
        ["Exact / verified matches", verified_count],
        ["Probable reserve / short-held", int((rec_df["status"] == "partial_reserve").sum())],
        ["Unresolved", int((rec_df["status"] == "unmatched").sum())],
        ["Processed bank amount", processed_amount],
        ["Absolute discrepant amount", amount_at_risk],
    ], columns=["Metric", "Value"]), use_container_width=True, hide_index=True)

    if exceptions.empty:
        st.success("Unresolved exception list: empty.")
    else:
        st.markdown("**Exception list**")
        st.dataframe(exceptions[["txn_id", "channel", "variance", "severity", "verdict", "note"]], use_container_width=True, hide_index=True)

    if metrics:
        with st.expander("Existing model-evaluation artifacts"):
            for name, payload in metrics.items():
                st.markdown(f"**{name}**")
                st.json(payload)

with tabs[4]:
    st.markdown('<div class="section-title">Audit Trail</div>', unsafe_allow_html=True)
    st.caption("Every financial number below comes from source records or deterministic calculations. Evidence is separated from model reasoning.")
    audit_rows = []
    for _, r in rec_df.iterrows():
        audit_rows.append({
            "timestamp": r["date"],
            "record": r["txn_id"],
            "event": "Settlement verification",
            "action": f"{r['verdict']} · {r['payout_id']}",
            "evidence": r["note"] or "Expected net matched actual bank deposit within tolerance.",
            "authority": "deterministic engine",
        })
    audit = pd.DataFrame(audit_rows).sort_values(["timestamp", "record"])
    st.dataframe(audit, use_container_width=True, hide_index=True)

    st.markdown("**Categorization evidence**")
    st.dataframe(cat_df[["txn_id", "category", "confidence", "cited_rule", "rationale"]], use_container_width=True, hide_index=True)

with tabs[5]:
    st.markdown('<div class="section-title">Ask the Agent · finance investigation</div>', unsafe_allow_html=True)
    st.caption("Ask questions that help explain a financial outcome. Tool-derived numbers remain authoritative; the agent does not perform financial arithmetic.")
    q = st.text_input("Investigation question", "Why is today's settlement lower than expected?")
    if st.button("Investigate", type="primary") and q:
        with st.spinner("Investigating evidence…"):
            out = ops_agent.run(q)
        st.markdown("**Investigation**")
        st.write(out["answer"])
        if out.get("trace"):
            with st.expander("Evidence / tool trace"):
                for t in out["trace"]:
                    st.code(f"{t['tool']}({t['args']}) → {t['result']}", language="json")
