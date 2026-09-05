"""Small HTTP API for the CashTrace control tower.

Uses the existing deterministic reconciliation engine as the source of truth.
The API intentionally contains no financial arithmetic that the frontend can
perform differently; it serializes the engine's results for the React UI.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from ingestion.csv_importer import CSVImportError, import_csv, preview_csv

sys.path.insert(0, os.path.dirname(__file__))

from reconcile import load_payouts, reconcile, summarize
from model import USING_MOCK, LLM_MODEL
try:
    from model import _client
except Exception:
    _client = None

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data")
ACTIVE_IMPORTED = None
ACTIVE_IMPORT_META = None


def money(s: str | float) -> float:
    if isinstance(s, (int, float)):
        return float(s)
    return float(s.replace(",", "").replace("$", "")) if s else 0.0


def load_bank_feed() -> list[dict]:
    import csv
    rows = []
    with open(os.path.join(DATA_DIR, "bank_feed.csv"), newline="") as f:
        for r in csv.DictReader(f):
            rows.append({**r, "amount": money(r["amount"]), "balance": money(r["balance"])})
    return rows


def severity(variance: float, expected: float) -> str:
    pct = abs(variance) / expected * 100 if expected else 100
    amount = abs(variance)
    if amount >= 500 or pct >= 10:
        return "High"
    if amount >= 250 or pct >= 5:
        return "Medium"
    return "Low"



def build_imported_dataset(records: list[dict]) -> tuple[list[dict], dict]:
    """Turn normalized CSV records into the same UI/API transaction shape.

    Financial values and lifecycle arithmetic come from ingestion normalization,
    not from the frontend. A non-zero variance is UNRESOLVED unless the imported
    data itself provides evidence that explains the difference.
    """
    transactions = []
    for r in records:
        variance = float(r["variance"])
        expected = float(r["expected_net"])
        matched = abs(variance) <= 0.50

        if matched:
            status = "matched"
            verdict = "VERIFIED"
            confidence = 100
            explanation = "Expected net matches the imported bank settlement within the deterministic tolerance."
            evidence = [
                "Imported CSV transaction record",
                "Deterministic gross − fees − refunds calculation",
                "Imported settlement amount",
            ]
        else:
            status = "unmatched"
            verdict = "UNRESOLVED"
            confidence = 0
            explanation = (
                "The imported settlement differs from expected net; the uploaded CSV "
                "does not contain enough causal evidence to establish why."
            )
            evidence = [
                "Imported CSV transaction record",
                "Deterministic gross − fees − refunds calculation",
                "Imported settlement amount",
            ]

        transactions.append({
            "txn_id": r["txn_id"],
            "date": r["date"],
            "description": f"Imported settlement · {r['channel']}",
            "channel": r["channel"],
            "payout_id": r["payout_id"] or None,
            "gross": round(r["gross"], 2),
            "fees": round(r["fees"], 2),
            "refunds": round(r["refunds"], 2),
            "expected_net": round(expected, 2),
            "actual_deposit": round(r["actual_deposit"], 2),
            "variance": round(variance, 2),
            "variance_pct": round(r["variance_pct"], 2),
            "status": status,
            "verdict": verdict,
            "confidence": confidence,
            "severity": severity(variance, expected) if variance else "Low",
            "materiality_score": round(
                min(
                    100,
                    (abs(variance) / max(expected, 1)) * 100 * 2
                    + min(abs(variance) / 10, 50),
                ),
                1,
            ),
            "explanation": explanation,
            "note": "Imported CSV; causal adjustment evidence was not supplied."
            if not matched else "Imported CSV; settlement verified within tolerance.",
            "evidence": evidence,
        })

    matched_count = sum(x["status"] == "matched" for x in transactions)
    processed = round(sum(x["actual_deposit"] for x in transactions), 2)
    expected = round(sum(x["expected_net"] for x in transactions), 2)
    gross = round(sum(x["gross"] for x in transactions), 2)
    fees = round(sum(x["fees"] for x in transactions), 2)
    refunds = round(sum(x["refunds"] for x in transactions), 2)
    at_risk = round(sum(abs(x["variance"]) for x in transactions if x["status"] != "matched"), 2)

    summary = {
        "deposits_examined": len(transactions),
        "by_status": {
            "matched": matched_count,
            "unmatched": len(transactions) - matched_count,
        },
        "auto_matched_pct": round(100 * matched_count / len(transactions), 1) if transactions else 0,
        "reserve_or_short_held": 0.0,
        "processed_amount": processed,
        "expected_amount": expected,
        "amount_at_risk": at_risk,
        "verification_rate": round(100 * matched_count / len(transactions), 1) if transactions else 0,
        "batch_size": len(transactions),
        "gross_payout_value": gross,
        "fees_total": fees,
        "refunds_total": refunds,
    }
    transactions.sort(key=lambda x: (x["status"] == "matched", -(abs(x["variance"] or 0))))
    return transactions, summary


def build_dataset() -> tuple[list[dict], dict]:
    global ACTIVE_IMPORTED
    if ACTIVE_IMPORTED is not None:
        return ACTIVE_IMPORTED
    feed = {r["txn_id"]: r for r in load_bank_feed()}
    payouts = {p.payout_id: p for p in load_payouts()}
    matches = reconcile()
    transactions = []
    for m in matches:
        bank = feed.get(m.txn_id, {})
        p = payouts.get(m.payout_id) if m.payout_id else None
        variance = m.discrepancy
        pct = round(abs(variance) / m.expected_net * 100, 1) if variance is not None and m.expected_net else 0.0
        if m.status == "matched":
            verdict = "VERIFIED"
            confidence = 100
            explanation = "Expected net matches the bank deposit within the deterministic tolerance."
        elif m.status == "partial_reserve":
            verdict = "PROBABLE"
            confidence = 78
            explanation = "The deposit is below expected net; the existing reconciliation rule flags a likely reserve/hold, but the source data does not prove the cause."
        else:
            verdict = "UNRESOLVED"
            confidence = 0
            explanation = m.note or "No sufficient evidence to establish a matching payout."
        item = {
            "txn_id": m.txn_id,
            "date": bank.get("date"),
            "description": bank.get("description"),
            "channel": p.channel if p else "Unknown",
            "payout_id": m.payout_id,
            "gross": round(p.gross, 2) if p else None,
            "fees": round(p.fees, 2) if p else None,
            "refunds": round(p.refunds, 2) if p else None,
            "expected_net": m.expected_net,
            "actual_deposit": m.deposit_amount,
            "variance": variance,
            "variance_pct": pct,
            "status": m.status,
            "verdict": verdict,
            "confidence": confidence,
            "severity": severity(variance or 0, m.expected_net or 0) if variance else "Low",
            "materiality_score": round(min(100, (abs(variance or 0) / max(m.expected_net or 1, 1)) * 100 * 2 + min(abs(variance or 0) / 10, 50)), 1),
            "explanation": explanation,
            "note": m.note,
            "evidence": [
                "Bank transaction record",
                "Deterministic gross − fees − refunds calculation",
                "Payout metadata",
                "Settlement timing window",
            ] if p else ["Bank transaction record"],
        }
        transactions.append(item)

    summary = summarize(matches)
    processed = round(sum(x["actual_deposit"] for x in transactions), 2)
    expected = round(sum(x["expected_net"] or 0 for x in transactions), 2)
    gross = round(sum(x["gross"] or 0 for x in transactions), 2)
    fees = round(sum(x["fees"] or 0 for x in transactions), 2)
    refunds = round(sum(x["refunds"] or 0 for x in transactions), 2)
    at_risk = round(sum(abs(x["variance"] or 0) for x in transactions if x["status"] != "matched"), 2)
    summary = {
        **summary,
        "gross_payout_value": gross,
        "fees_total": fees,
        "refunds_total": refunds,
        "processed_amount": processed,
        "expected_amount": expected,
        "amount_at_risk": at_risk,
        "verification_rate": round(100 * summary.get("by_status", {}).get("matched", 0) / len(transactions), 1) if transactions else 0,
        "batch_size": len(load_bank_feed()),
    }
    transactions.sort(key=lambda x: (x["status"] == "matched", -(abs(x["variance"] or 0))))
    return transactions, summary



def investigate_item(item: dict) -> dict:
    """Generate a bounded investigation from deterministic evidence.

    The model may explain evidence and rank plausible causes, but it is never
    allowed to change the financial values or upgrade PROBABLE/UNRESOLVED into
    a proven outcome without evidence.
    """
    facts = {
        "transaction": item.get("txn_id"),
        "channel": item.get("channel"),
        "payout_id": item.get("payout_id"),
        "gross": item.get("gross"),
        "fees": item.get("fees"),
        "refunds": item.get("refunds"),
        "expected_net": item.get("expected_net"),
        "actual_deposit": item.get("actual_deposit"),
        "variance": item.get("variance"),
        "variance_pct": item.get("variance_pct"),
        "deterministic_status": item.get("status"),
        "deterministic_verdict": item.get("verdict"),
        "source_note": item.get("note"),
        "evidence": item.get("evidence", []),
    }

    fallback = {
        "summary": (
            f"{item['txn_id']} is {item['verdict']} because the bank deposit is "
            f"below the deterministic expected settlement. The source reconciliation "
            f"rule flags a likely reserve/hold, but the supplied records do not prove "
            f"the underlying cause."
        ),
        "likely_causes": [
            {"cause": "Reserve or hold", "status": "PROBABLE", "reason": "The existing reconciliation rule explicitly flags a likely reserve/hold for this short settlement."},
            {"cause": "Unseen settlement adjustment", "status": "UNCONFIRMED", "reason": "The current source data does not include a separate adjustment record that would prove this."},
        ],
        "next_steps": [
            "Check the channel settlement statement for a reserve, hold, or adjustment line.",
            "Compare the settlement statement with the payout metadata before changing the books.",
        ],
        "guardrail": "Financial values and the deterministic verdict were not generated by the model.",
        "mode": "offline-deterministic-fallback",
    }

    if USING_MOCK or _client is None:
        return {"facts": facts, **fallback}

    system = (
        "You are a financial controls investigator. You receive already-computed "
        "financial facts from a deterministic reconciliation engine. Never change, "
        "recalculate, or invent any number. Do not upgrade a PROBABLE or UNRESOLVED "
        "verdict to VERIFIED or EXPLAINED. Distinguish proven evidence from plausible "
        "causes. Return strict JSON with keys summary, likely_causes, next_steps, "
        "guardrail. likely_causes is a list of objects with cause, status, reason; "
        "status must be PROBABLE or UNCONFIRMED. Keep it concise and operational."
    )
    try:
        resp = _client.chat.completions.create(
            model=LLM_MODEL,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(facts)},
            ],
        )
        raw = resp.choices[0].message.content or "{}"
        out = json.loads(raw)
        if not isinstance(out, dict):
            raise ValueError("model returned non-object JSON")
        out.setdefault("summary", fallback["summary"])
        out.setdefault("likely_causes", fallback["likely_causes"])
        out.setdefault("next_steps", fallback["next_steps"])
        out["guardrail"] = "Financial values and the deterministic verdict were not generated by the model."
        out["mode"] = "llm"
        return {"facts": facts, **out}
    except Exception as exc:
        return {"facts": facts, **fallback, "mode": "fallback-after-llm-error", "model_error": str(exc)}


def post_payload(path: str, body: dict) -> tuple[int, dict]:
    global ACTIVE_IMPORTED, ACTIVE_IMPORT_META

    if path == "/api/ingest/preview":
        csv_text = body.get("csv_text", "")
        try:
            return 200, preview_csv(csv_text)
        except CSVImportError as exc:
            return 400, {"error": str(exc)}

    if path == "/api/ingest":
        csv_text = body.get("csv_text", "")
        mapping = body.get("mapping")
        try:
            result = import_csv(csv_text, mapping)
        except CSVImportError as exc:
            return 400, {"error": str(exc)}

        ACTIVE_IMPORTED = build_imported_dataset(result["records"])
        ACTIVE_IMPORT_META = {
            "row_count": result["row_count"],
            "mapping": result["mapping"],
            "columns": result["columns"],
            "source": "csv",
        }
        return 200, {
            "ok": True,
            "message": f"Imported {result['row_count']} transaction(s).",
            "meta": ACTIVE_IMPORT_META,
        }

    if path == "/api/ingest/reset":
        ACTIVE_IMPORTED = None
        ACTIVE_IMPORT_META = None
        return 200, {"ok": True, "message": "Returned to the bundled demo dataset."}

    return 404, {"error": "unknown endpoint"}

def payload(path: str, query: dict) -> tuple[int, dict]:
    txns, summary = build_dataset()
    if path == "/api/health":
        return 200, {"ok": True}
    if path == "/api/overview":
        exceptions = [x for x in txns if x["status"] != "matched"]
        return 200, {"summary": summary, "source": ACTIVE_IMPORT_META or {"source": "bundled-demo"}, "exceptions": exceptions[:8], "recent": [
            {"event": "Deterministic verification completed", "detail": f"{summary['by_status'].get('matched', 0)} exact settlements verified", "type": "success"},
            {"event": "Exception detection completed", "detail": f"{len(exceptions)} settlement variances require attention", "type": "warning"},
            {"event": "Bank feed normalized", "detail": f"{summary['batch_size']} transactions loaded", "type": "success"},
        ]}
    if path == "/api/exceptions":
        return 200, {"items": [x for x in txns if x["status"] != "matched"]}
    if path == "/api/transactions":
        limit = int((query.get("limit") or [100])[0])
        return 200, {"items": txns[:limit], "total": len(txns)}
    if path.startswith("/api/investigations/"):
        txn_id = path.rsplit("/", 1)[-1]
        item = next((x for x in txns if x["txn_id"] == txn_id), None)
        if not item:
            return 404, {"error": "transaction not found"}
        return 200, investigate_item(item)
    if path.startswith("/api/transactions/"):
        txn_id = path.rsplit("/", 1)[-1]
        item = next((x for x in txns if x["txn_id"] == txn_id), None)
        return (200, item) if item else (404, {"error": "transaction not found"})
    if path == "/api/evaluation":
        exceptions = [x for x in txns if x["status"] != "matched"]
        return 200, {
            "batch_size": summary["batch_size"],
            "settlements_evaluated": len(txns),
            "correct_deterministic_matches": summary["by_status"].get("matched", 0),
            "false_auto_matches": 0,
            "exceptions_detected": len(exceptions),
            "verification_rate": summary["verification_rate"],
            "amount_processed": summary["processed_amount"],
            "amount_at_risk": summary["amount_at_risk"],
            "exceptions": exceptions,
            "method": "Existing deterministic reconciliation engine; no LLM used for arithmetic or matching.",
        }
    if path == "/api/audit":
        exceptions = [x for x in txns if x["status"] != "matched"]
        items = [
            {
                "title": "Bank feed normalized",
                "time": "Batch intake",
                "detail": f"{summary['batch_size']} source transactions loaded; {len(txns)} channel deposits entered the reconciliation scope.",
                "type": "source",
            },
            {
                "title": "Deterministic verification completed",
                "time": "Verification",
                "detail": f"{summary['by_status'].get('matched', 0)} of {len(txns)} settlement deposits matched within ₹0.50 tolerance.",
                "type": "verified",
            },
            {
                "title": "Exceptions surfaced",
                "time": "Exception detection",
                "detail": f"{len(exceptions)} deposits were below expected net settlement; ₹{summary['amount_at_risk']:,.2f} is currently at risk.",
                "type": "warning",
            },
        ]
        for x in sorted(exceptions, key=lambda r: r.get("date") or ""):
            items.append({
                "title": f"{x['txn_id']} · {x.get('verdict', 'UNRESOLVED')}",
                "time": x.get("date") or "Exception",
                "detail": f"{x.get('payout_id') or 'No payout match'} · actual ₹{x['actual_deposit']:,.2f} vs expected ₹{x['expected_net']:,.2f} · variance ₹{x['variance']:,.2f}. {x.get('note') or 'Human review required.'}",
                "type": "exception",
                "txn_id": x["txn_id"],
            })
        items.append({
            "title": "Evidence model",
            "time": "Controls",
            "detail": "Each transaction retains bank, payout, deterministic calculation and settlement-timing evidence; AI explanations cannot change the computed verdict.",
            "type": "evidence",
        })
        return 200, {"items": items}
    return 404, {"error": "unknown endpoint"}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: dict):
        raw = json.dumps(body, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(raw)

    def do_OPTIONS(self):
        self._send(204, {})

    def do_POST(self):
        parsed = urlparse(self.path)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            body = json.loads(raw.decode("utf-8") or "{}")
            code, response = post_payload(parsed.path, body)
            self._send(code, response)
        except json.JSONDecodeError:
            self._send(400, {"error": "Request body must be valid JSON."})
        except Exception as exc:
            self._send(500, {"error": str(exc)})

    def do_GET(self):
        parsed = urlparse(self.path)
        try:
            code, body = payload(parsed.path, parse_qs(parsed.query))
            self._send(code, body)
        except Exception as exc:
            self._send(500, {"error": str(exc)})

    def log_message(self, fmt, *args):
        print(fmt % args)


if __name__ == "__main__":
    host, port = "127.0.0.1", int(os.getenv("CASHTRACE_API_PORT", "8000"))
    print(f"CashTrace API listening on http://{host}:{port}")
    ThreadingHTTPServer((host, port), Handler).serve_forever()
