"""Convert flexible financial CSVs into the CashTrace schema."""
from __future__ import annotations
import csv, io, math
from datetime import datetime
from .column_mapper import normalize_mapping, suggest_column_mapping

CANONICAL_COLUMNS = [
    "txn_id","date","channel","payout_id","gross","fees","refunds",
    "actual_deposit","expected_net","variance","variance_pct",
]

class CSVImportError(ValueError):
    pass

def _number(value, field, row):
    if value is None or str(value).strip() == "":
        return 0.0
    text = str(value).strip().replace(",", "")
    for symbol in ("₹", "$", "€", "£"):
        text = text.replace(symbol, "")
    try:
        number = float(text.strip())
    except ValueError as exc:
        raise CSVImportError(f"Row {row}: '{value}' is not a valid number for {field}.") from exc
    if not math.isfinite(number):
        raise CSVImportError(f"Row {row}: '{value}' is not finite.")
    return round(number, 2)

def _date(value, row):
    if value is None or not str(value).strip():
        raise CSVImportError(f"Row {row}: date is required.")
    text = str(value).strip()
    for fmt in ("%Y-%m-%d","%Y/%m/%d","%d-%m-%Y","%d/%m/%Y","%m/%d/%Y",
                "%Y-%m-%d %H:%M:%S","%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            pass
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10]
    raise CSVImportError(f"Row {row}: unsupported date '{value}'.")

def _read(csv_text):
    if not csv_text or not csv_text.strip():
        raise CSVImportError("The uploaded CSV is empty.")
    try:
        reader = csv.DictReader(io.StringIO(csv_text))
        headers = reader.fieldnames or []
        if not headers:
            raise CSVImportError("The CSV has no header row.")
        return headers, list(reader)
    except csv.Error as exc:
        raise CSVImportError(f"Could not parse CSV: {exc}") from exc

def normalize_rows(rows, mapping):
    mapping = normalize_mapping(mapping)
    required = ["txn_id","date","gross","actual_deposit"]
    missing = [x for x in required if not mapping.get(x)]
    if missing:
        raise CSVImportError("Missing required column mapping: " + ", ".join(missing))

    output = []
    for row_no, raw in enumerate(rows, start=2):
        def get(field, default=""):
            source = mapping.get(field)
            return raw.get(source, default) if source else default

        txn_id = str(get("txn_id")).strip()
        if not txn_id:
            raise CSVImportError(f"Row {row_no}: transaction ID is required.")

        gross = _number(get("gross"), "gross", row_no)
        fees = _number(get("fees"), "fees", row_no)
        refunds = _number(get("refunds"), "refunds", row_no)
        actual = _number(get("actual_deposit"), "actual_deposit", row_no)
        expected = round(gross - fees - refunds, 2)
        variance = round(actual - expected, 2)
        variance_pct = round(variance / expected * 100, 2) if expected else 0.0

        output.append({
            "txn_id": txn_id,
            "date": _date(get("date"), row_no),
            "channel": str(get("channel", "Unknown")).strip() or "Unknown",
            "payout_id": str(get("payout_id")).strip(),
            "gross": gross,
            "fees": fees,
            "refunds": refunds,
            "actual_deposit": actual,
            "expected_net": expected,
            "variance": variance,
            "variance_pct": variance_pct,
        })

    if not output:
        raise CSVImportError("The CSV contains no data rows.")
    return output

def preview_csv(csv_text):
    headers, rows = _read(csv_text)
    return {
        "headers": headers,
        "row_count": len(rows),
        "suggestions": suggest_column_mapping(headers),
        "sample": rows[:5],
    }

def import_csv(csv_text, mapping=None):
    headers, rows = _read(csv_text)
    if mapping is None:
        suggestions = suggest_column_mapping(headers)
        mapping = {k: v["source"] for k, v in suggestions.items()}
    records = normalize_rows(rows, mapping)
    return {
        "records": records,
        "row_count": len(records),
        "columns": CANONICAL_COLUMNS,
        "mapping": normalize_mapping(mapping),
    }
