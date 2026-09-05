"""Flexible column detection for CashTrace CSV imports."""
import re
from difflib import SequenceMatcher

ALIASES = {
    "txn_id": ["txn_id","transaction_id","transaction","transactionid","txn","id","order_id","orderid","reference","reference_id"],
    "date": ["date","transaction_date","transactiondate","settlement_date","settlementdate","payment_date","paymentdate","created_at","created_date"],
    "channel": ["channel","platform","gateway","marketplace","source","merchant","payment_channel"],
    "payout_id": ["payout_id","payoutid","payout","settlement_id","settlementid","settlement","batch_id","batchid"],
    "gross": ["gross","gross_amount","grossamount","sales","sale_amount","amount","order_amount","payment_amount","total_amount"],
    "fees": ["fees","fee","fee_amount","feeamount","gateway_fee","processing_fee","platform_fee","commission","charges"],
    "refunds": ["refunds","refund","refund_amount","refundamount","adjustment","adjustments","returns","return_amount"],
    "actual_deposit": ["actual_deposit","actualdeposit","actual_settlement","actualsettlement","settled_amount","settledamount","received","received_amount","bank_amount","bank_deposit","deposit","deposit_amount","bank_settlement"],
    "evidence_type": ["evidence_type","evidencetype","resolution_type","resolutiontype","verdict_type","classification"],
    "evidence": ["evidence","evidence_note","evidencenote","resolution_evidence","resolutionevidence","investigation_evidence","adjustment_note","adjustmentnote","notes","note"],
}

def _norm(value):
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")

def _score(header, alias):
    h, a = _norm(header), _norm(alias)
    if h == a:
        return 1.0
    if h.replace("_", "") == a.replace("_", ""):
        return 0.97
    score = SequenceMatcher(None, h, a).ratio()
    if a in h or h in a:
        score = max(score, 0.90)
    return score

def suggest_column_mapping(headers):
    """Suggest canonical CashTrace fields from arbitrary CSV headers."""
    headers = [str(h) for h in headers if str(h).strip()]
    suggestions, used = {}, set()
    candidates = []
    for canonical, aliases in ALIASES.items():
        for header in headers:
            candidates.append((max(_score(header, a) for a in aliases), canonical, header))
    for score, canonical, header in sorted(candidates, reverse=True):
        if canonical in suggestions or header in used or score < 0.72:
            continue
        suggestions[canonical] = {"source": header, "confidence": round(score, 2)}
        used.add(header)
    return suggestions

def normalize_mapping(mapping):
    result = {}
    for canonical, value in (mapping or {}).items():
        source = value.get("source") if isinstance(value, dict) else value
        if source:
            result[str(canonical)] = str(source)
    return result
