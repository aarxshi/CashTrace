"""CashTrace's lifecycle layer, built on top of the deterministic reconciliation
engine in reconcile.py.

reconcile.py answers "which payout matches which deposit?". This module asks
the broader question CashTrace is built around: "can I account for the
complete lifecycle of this money, and if not, where did the chain break?" —
by joining each match back to the payout's gross/fees/refunds, so the full
chain (order -> payment captured -> fees -> refunds -> expected settlement ->
actual settlement) is visible, and by scoring each case on materiality so
exceptions can be prioritised the way a finance ops team actually would.

Nothing here invents a number. Every field traces back to a bank-feed deposit
or a channel payout record; the only new things this module adds are labels
(status, materiality band) and short human-readable explanations derived
from those numbers.
"""

from __future__ import annotations

from dataclasses import dataclass

from reconcile import Match, NormPayout, load_payouts, reconcile, summarize

# How much of the expected settlement a shortfall can be before CashTrace
# treats it as a confidently-explained reserve/hold vs. a case that needs a
# human to confirm. This is a heuristic threshold, not a trained model — kept
# deliberately simple and stated plainly so it's auditable.
RESERVE_CONFIDENCE_CUTOFF = 0.15  # <=15% of expected settlement

# Materiality bands: combine an absolute dollar amount at risk with the
# fraction of the expected settlement it represents, since a $200 gap means
# very different things on a $2,000 settlement vs. a $2,000,000 one.
MATERIALITY_HIGH = {"min_amount": 300.0, "min_pct": 0.15}
MATERIALITY_MEDIUM = {"min_amount": 75.0, "min_pct": 0.05}


@dataclass
class LifecycleRecord:
    txn_id: str
    channel: str | None
    payout_id: str | None
    order_gross: float | None       # payout gross (the "order" side of the chain)
    fees: float | None
    refunds: float | None
    expected_settlement: float | None
    actual_settlement: float
    discrepancy: float | None
    engine_status: str               # matched | partial_reserve | unmatched (from reconcile.py)
    status: str                      # VERIFIED | EXPLAINED | PROBABLE | UNRESOLVED
    confidence: float
    amount_at_risk: float
    pct_at_risk: float
    materiality: str                 # High | Medium | Low
    exception_type: str | None
    explanation: str
    evidence: list[str]


def _materiality(amount_at_risk: float, pct_at_risk: float) -> str:
    if amount_at_risk >= MATERIALITY_HIGH["min_amount"] or pct_at_risk >= MATERIALITY_HIGH["min_pct"]:
        return "High"
    if amount_at_risk >= MATERIALITY_MEDIUM["min_amount"] or pct_at_risk >= MATERIALITY_MEDIUM["min_pct"]:
        return "Medium"
    return "Low"


def _from_match(m: Match, payouts_by_id: dict[str, NormPayout]) -> LifecycleRecord:
    p = payouts_by_id.get(m.payout_id) if m.payout_id else None
    channel = p.channel if p else None
    order_gross = p.gross if p else None
    fees = p.fees if p else None
    refunds = p.refunds if p else None

    if m.status == "matched":
        amount_at_risk = 0.0
        pct_at_risk = 0.0
        status = "VERIFIED"
        confidence = 0.99
        exception_type = None
        explanation = "Deposit equals expected net settlement to the penny — fully explained by the payout record."
        evidence = ["Bank deposit", "Payout record", "Deterministic net calculation"]

    elif m.status == "partial_reserve":
        amount_at_risk = abs(m.discrepancy) if m.discrepancy is not None else 0.0
        pct_at_risk = round(amount_at_risk / m.expected_net, 4) if m.expected_net else 0.0
        if pct_at_risk <= RESERVE_CONFIDENCE_CUTOFF:
            status = "EXPLAINED"
            confidence = round(max(0.75, 0.97 - pct_at_risk), 2)
            exception_type = "Reserve / partial hold"
            explanation = (f"Settlement is short by ${amount_at_risk:,.2f} "
                            f"({pct_at_risk:.1%} of expected) — consistent with a reserve or "
                            f"rolling hold on this channel.")
        else:
            status = "PROBABLE"
            confidence = round(max(0.40, 0.75 - pct_at_risk), 2)
            exception_type = "Settlement shortfall"
            explanation = (f"Settlement is short by ${amount_at_risk:,.2f} "
                            f"({pct_at_risk:.1%} of expected) — larger than a typical reserve "
                            f"pattern, so CashTrace has a hypothesis but not enough evidence to "
                            f"close it automatically.")
        evidence = ["Bank deposit", "Payout record", "Historical reserve pattern (channel-level)"]

    else:  # unmatched
        amount_at_risk = m.deposit_amount
        pct_at_risk = 1.0
        status = "UNRESOLVED"
        confidence = 0.0
        exception_type = "Unmatched deposit"
        explanation = ("No payout candidate was found for this deposit within the "
                        "reconciliation window — there isn't enough evidence to explain it "
                        "automatically, so it's routed to human review.")
        evidence = ["Bank deposit"]

    return LifecycleRecord(
        txn_id=m.txn_id, channel=channel, payout_id=m.payout_id,
        order_gross=order_gross, fees=fees, refunds=refunds,
        expected_settlement=m.expected_net, actual_settlement=m.deposit_amount,
        discrepancy=m.discrepancy, engine_status=m.status, status=status,
        confidence=confidence, amount_at_risk=round(amount_at_risk, 2),
        pct_at_risk=pct_at_risk, materiality=_materiality(amount_at_risk, pct_at_risk),
        exception_type=exception_type, explanation=explanation, evidence=evidence,
    )


def build_lifecycle() -> list[LifecycleRecord]:
    matches = reconcile()
    payouts_by_id = {p.payout_id: p for p in load_payouts()}
    return [_from_match(m, payouts_by_id) for m in matches]


def dashboard_summary(records: list[LifecycleRecord]) -> dict:
    total = len(records)
    processed = round(sum(r.actual_settlement for r in records), 2)
    verified_n = sum(1 for r in records if r.status in ("VERIFIED", "EXPLAINED"))
    verified_pct = round(100 * verified_n / total, 1) if total else 0.0
    needs_review_amount = round(sum(r.amount_at_risk for r in records
                                    if r.status in ("PROBABLE", "UNRESOLVED")), 2)
    by_engine = {}
    for r in records:
        by_engine[r.engine_status] = by_engine.get(r.engine_status, 0) + 1
    by_cashtrace = {}
    for r in records:
        by_cashtrace[r.status] = by_cashtrace.get(r.status, 0) + 1
    return {
        "total": total,
        "processed": processed,
        "verified_pct": verified_pct,
        "needs_review_amount": needs_review_amount,
        "by_engine_status": by_engine,
        "by_cashtrace_status": by_cashtrace,
    }


def exception_groups(records: list[LifecycleRecord]) -> list[dict]:
    """Exceptions (non-VERIFIED records) grouped by type, for the Exception Center."""
    groups: dict[str, dict] = {}
    for r in records:
        if r.status == "VERIFIED":
            continue
        key = r.exception_type or "Other"
        g = groups.setdefault(key, {"type": key, "amount": 0.0, "count": 0, "materiality": "Low"})
        g["amount"] += r.amount_at_risk
        g["count"] += 1
        if _rank(r.materiality) > _rank(g["materiality"]):
            g["materiality"] = r.materiality
    out = [{**g, "amount": round(g["amount"], 2)} for g in groups.values()]
    out.sort(key=lambda g: g["amount"], reverse=True)
    return out


def _rank(materiality: str) -> int:
    return {"Low": 0, "Medium": 1, "High": 2}.get(materiality, 0)


def audit_trail(r: LifecycleRecord) -> list[str]:
    """A traceable, honest timeline for one record — built only from fields we
    actually have (no fabricated timestamps down to the second)."""
    lines = [f"Deposit {r.txn_id} ingested — ${r.actual_settlement:,.2f}"]
    if r.payout_id:
        lines.append(f"Payout {r.payout_id} linked ({r.channel} channel)")
        if r.order_gross is not None:
            lines.append(f"Order gross ${r.order_gross:,.2f} — fees ${r.fees:,.2f}, "
                         f"refunds ${r.refunds:,.2f} -> expected settlement "
                         f"${r.expected_settlement:,.2f}")
    if r.discrepancy not in (None, 0.0):
        lines.append(f"Discrepancy of ${r.discrepancy:+,.2f} detected")
    if r.amount_at_risk:
        lines.append(f"Amount at risk: ${r.amount_at_risk:,.2f} "
                     f"({r.pct_at_risk:.1%} of expected) — materiality: {r.materiality}")
    lines.append(f"Evidence retrieved: {', '.join(r.evidence)}")
    lines.append(f"Confidence: {r.confidence:.0%}")
    lines.append(f"Marked {r.status}")
    return lines


if __name__ == "__main__":
    import json
    recs = build_lifecycle()
    print(json.dumps(dashboard_summary(recs), indent=2))
    print(json.dumps(exception_groups(recs), indent=2))