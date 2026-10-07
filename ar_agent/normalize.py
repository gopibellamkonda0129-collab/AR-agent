"""Normalization: convert loader candidates into a schema'd DataFrame.

Strategy:

1. TABLES first. For every table, scan rows for a header row that matches
   >= 4 of the expected columns (fuzzy synonym matching). The winning table
   becomes the dataset; other tables with the same width are appended as
   more rows (e.g. multi-page PDFs).

2. KEY-VALUE fallback. If no table header matched, the file is treated as
   one or more individual invoices (a single PDF/DOCX invoice, OCR text,
   an email excerpt, ...). Field patterns are pulled from the raw text and
   collapsed to a single row so the customer still shows up in triage.

3. Otherwise raise a friendly error listing what WAS found.
"""
from __future__ import annotations

import re
import unicodedata

import pandas as pd

# canonical key -> accepted synonym set (normalized: lowercase, alnum only)
SCHEMA = {
    "customer_name": [
        "customername", "customer", "client", "company", "companyname",
        "accountname", "account", "billto", "name", "clientcompany", "company",
    ],
    "invoice_number": [
        "invoicenumber", "invoicenum", "invoiceno", "invoiceno#",
        "invoice#", "invoice", "number", "no", "invoiceid", "id", "ref",
        "invoicereference", "inno",
    ],
    "invoice_date": [
        "invoicedate", "dateissued", "issuedate", "invoicedatecreated",
        "creationdate", "date", "createdate", "created", "posteddate",
        "issued", "invoicethen", "invoicestartdate",
    ],
    "due_date": [
        "duedate", "paymentduedate", "paymentdue", "due", "deadline",
        "datepayable", "paymentdate", "termsduedate", "finalpaymentdate",
        "datedue",
    ],
    "amount": [
        "amount", "total", "grandtotal", "amountdue", "balance", "totalamount",
        "invoicetotal", "totaldue", "amountoutstanding", "totalbalance",
        "invoiceamount", "chargeamount", "grandtotaldue", "amountvalue", "totalamountdue",
    ],
    "amount_paid": [
        "amountpaid", "paidamount", "paid", "payment", "payments", "totalpaid",
        "amountreceived", "paymentreceived", "paidtilldate", "aapplyamount",
        "credited", "credits",
    ],
    "status": [
        "status", "paymentstatus", "state", "condition", "statusvalue",
        "invoicestatus", "statuscode", "paymentstate",
    ],
    "contact_email": [
        "contactemail", "email", "emailaddress", "billingemail",
        "accountemail", "emailid", "mail", "contactemailaddress",
    ],
}

# more specific keys win when two keys could plausibly match one header
KEY_ORDER = [
    "invoice_number",
    "invoice_date",
    "due_date",
    "amount_paid",
    "amount",
    "status",
    "contact_email",
    "customer_name",
]

# keys allowed to use single-token containment (customer/email/status cells
# are never ambiguous with amounts or dates)
SINGLE_TOKEN_KEYS = {"customer_name", "contact_email", "status"}

MIN_HEADER_MATCH = 4


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(ch for ch in s if ch.isalnum() or ch.isspace())
    return re.sub(r"\s+", "", s.lower())


def _tokens(s: str) -> list[str]:
    return [t for t in re.split(r"[^A-Za-z0-9]+", str(s).lower()) if t]


def _match_key(cell: str) -> str | None:
    c_norm = _norm(cell)
    if not c_norm:
        return None
    c_tokens = _tokens(cell)

    # phase 1: exact normalized match (handles compressed headers like
    # "amountpaid", "invoiceno", "duedate", "grandtotal")
    for key in KEY_ORDER:
        for s in SCHEMA[key]:
            if c_norm == _norm(s):
                return key

    # phase 2a: consecutive token containment for multi-word cells, e.g.
    # "Total Amount Due" -> amount, "Payment Received" -> amount_paid
    for key in KEY_ORDER:
        for s in SCHEMA[key]:
            st = _tokens(s)
            if len(st) < 2:
                continue
            for i in range(len(c_tokens) - len(st) + 1):
                if c_tokens[i:i + len(st)] == st:
                    return key

    # phase 2b: single-token containment only for columns where a bare word
    # can never be confused with amounts/dates (customer/email/status)
    for key in KEY_ORDER:
        if key not in SINGLE_TOKEN_KEYS:
            continue
        for s in SCHEMA[key]:
            st = _tokens(s)
            if len(st) != 1:
                continue
            if st[0] in c_tokens:
                return key
    return None


def _header_score(row: list[str]) -> int:
    return sum(1 for cell in row if _match_key(cell))


def _find_header(rows: list[list[str]]) -> tuple[int, dict[str, int]]:
    """Return (header_row_index, {schema_key: column_index}) for the best row."""
    best_idx, best_map, best_score = -1, {}, 0
    for i, row in enumerate(rows):
        mapping = {}
        for col, cell in enumerate(row):
            key = _match_key(cell)
            if key and key not in mapping:
                mapping[key] = col
        if len(mapping) >= MIN_HEADER_MATCH and len(mapping) > best_score:
            best_idx, best_map, best_score = i, mapping, len(mapping)
    return best_idx, best_map


def _collapse_to_schema(rows: list[list[str]]) -> pd.DataFrame | None:
    """First table with a strong header wins; append same-width tables."""
    for tab in rows:
        idx, mapping = _find_header(tab)
        if idx < 0:
            continue
        width = len(tab[idx])
        data = [r[:width] for r in tab[idx + 1:]]
        out = pd.DataFrame(data, columns=[f"col_{i}" for i in range(width)])
        rename = {f"col_{v}": k for k, v in mapping.items()}
        out = out.rename(columns=rename)
        return out
    return None


# ---------------------------------------------------------------------------
# key-value single-invoice fallback (also segments multi-invoice documents)
# ---------------------------------------------------------------------------

_DATE_PAT = r"(\d{1,4}[/.-]\d{1,2}[/.-]\d{2,4}|[A-Za-z]{3,}\s+\d{1,2},?\s+\d{4})"
_MONEY_PAT = r"([\d,]+(?:\.\d{1,2})?)"

_EMAIL_RE = re.compile(r"([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})")
_INV_NO_RE = re.compile(
    r"(?i)\binvoice\s*(?:number\s*|no\.?\s*|#\s*|id\s*)?"
    r"[:#]?\s*([#A-Za-z0-9][A-Za-z0-9\-/_.]{1,40})"
)
_INV_DATE_RE = re.compile(r"(?i)\b(?:invoice|issue|issued)\s+date\s*(?:[:#])?\s*" + _DATE_PAT)
_DUE_RE = re.compile(
    r"(?i)\b(?:due\s+date|payment\s+due\s*date|date\s+due|payable\s+date|due)"
    r"\s*(?:[:#])?\s*" + _DATE_PAT
)
_TOTAL_RE = re.compile(
    r"(?i)\b(?:grand\s+total|total\s+(?:amount|due)|amount\s+due|balance\s+due|"
    r"total\s+amount|total|amount\s+payable)"
    r"\s*(?:[:#])?\s*(?:[$€£]\s*)?(" + _MONEY_PAT[1:-1] + r")"
)
_PAID_RE = re.compile(
    r"(?i)\b(?:amount\s+paid|total\s+paid|paid|payment\s+received|received)"
    r"\s*(?:[:#])?\s*(?:[$€£]\s*)?(" + _MONEY_PAT[1:-1] + r")"
)
_STATUS_RE = re.compile(r"(?i)\b(?:invoice\s+)?status\s*(?:[:#])?\s*([A-Za-z]+)")
_BILLTO_RE = re.compile(
    r"(?i)\b(?:bill\s*to|customer(?:\s+name|\s+id)?|sold\s*to|client)\s*(?:[:#])?\s*"
)
_PAGE_BREAK = r"\f|\n\s*={3,}\s*PAGE\s*={3,}\s*\n"

# words that can never be a company name
_NAME_JUNK = {
    "invoice", "invoices", "details", "detail", "summary", "information",
    "customer", "client", "billing", "shipping", "payment", "contact",
    "date", "amount", "total", "status", "balance", "due", "issued",
    "the", "company", "information", "no", "number", "inc", "llc",
    "please", "terms", "thank", "remit",
}


def _parse_money(raw: str) -> float:
    try:
        return float(raw.replace(",", "").strip())
    except ValueError:
        return 0.0


def _clean_date(raw: str) -> str:
    raw = raw.strip()
    # normalize month name dates like "Sep 8, 2026"
    try:
        import datetime as _dt
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%b %d, %Y", "%B %d, %Y", "%d-%b-%Y"):
            try:
                return str(_dt.datetime.strptime(raw, fmt).date())
            except ValueError:
                continue
    except Exception:
        pass
    return raw


def _looks_like_date(s: str) -> bool:
    return bool(
        re.match(r"^\d{1,4}([/.\-])\d{1,2}\1\d{1,4}$", s)
        or re.match(r"^[A-Za-z]{3,}\s+\d{1,2},?\s+\d{2,4}$", s)
    )


def _is_invoice_marker(line: str) -> bool:
    m = _INV_NO_RE.search(line)
    if not m:
        return False
    rid = m.group(1).strip().lstrip("#").strip()
    if _looks_like_date(rid):
        return False  # "Invoice Date: 2026-08-20" is not an invoice number
    low = rid.lower()
    if low.startswith(("details", "number", "date", "total", "amount",
                       "status", "summary", "issued", "page", "id")):
        return False  # section headers / labels, not IDs
    return len(rid) >= 2 and any(ch.isdigit() for ch in rid)


def _valid_name(raw: str) -> str | None:
    name = raw.strip().strip(":.#-").strip()
    if not name:
        return None
    if "@" in name or "http" in name.lower():
        return None
    low = name.lower()
    if low in _NAME_JUNK or len(name) < 3:
        return None
    # reject "label: value" style leftovers
    if len(re.split(r"\s+", name)) <= 2 and low.split()[0] in (
        "bill", "customer", "sold", "client", "invoice", "payment"
    ):
        return None
    return name[:60]


def _blocks_from_text(text: str) -> list[list[str]]:
    """Split a document into per-invoice line blocks.

    A new block starts at a strong invoice marker ("Invoice #001",
    "Invoice Number: INV-9", "Invoice No 0421") or, when pages are
    present, at a page that begins with invoice-like headings.
    """
    pages = re.split(_PAGE_BREAK, text)
    blocks: list[list[str]] = []

    for pidx, page in enumerate(pages):
        lines = [l.strip() for l in page.splitlines() if l.strip()]
        if not lines:
            continue

        marker_idx = [i for i, l in enumerate(lines) if _is_invoice_marker(l)]

        if not marker_idx:
            # single invoice (or a continuation page): whole page is one block
            blocks.append(lines)
            continue

        for k, mi in enumerate(marker_idx):
            end = marker_idx[k + 1] if k + 1 < len(marker_idx) else len(lines)
            seg = lines[mi:end]
            # attach any header lines (issuer name, address, logo text) that
            # appear before the FIRST invoice marker to that invoice
            if k == 0:
                seg = lines[:mi] + seg
            blocks.append(seg)

    return blocks


def _extract_customer(lines: list[str]) -> tuple[str | None, int]:
    """Return (customer_name or None, line_index_of_contact_email).

    Handles 'Bill To:' labels whose value sits on the FOLLOWING line and
    refuses labels like 'INVOICE DETAILS' that are just section headers.
    """
    for i, line in enumerate(lines):
        m = _BILLTO_RE.search(line)
        if not m:
            continue
        rest = line[m.end():].strip().strip(":.-").strip()
        candidate = _valid_name(rest)
        if candidate:
            return candidate, i
        # empty label -> value is on the next non-empty, non-label line
        for j in range(i + 1, min(i + 4, len(lines))):
            nxt = lines[j]
            if _BILLTO_RE.search(nxt) or _is_invoice_marker(nxt):
                break
            if ":" in nxt or "@" in nxt:
                continue
            candidate = _valid_name(nxt)
            if candidate:
                return candidate, i
    return None, -1


def _extract_email(lines: list[str], customer_line: int) -> str:
    """Prefer the CUSTOMER's email (after the Bill To block) over any other."""
    picked, best_idx = "", -1
    for i, line in enumerate(lines):
        m = _EMAIL_RE.search(line)
        if not m:
            continue
        email = m.group(1).lower()
        if i >= customer_line > best_idx and _valid_email(email):
            picked, best_idx = email, i
    if picked:
        return picked
    for line in lines:
        m = _EMAIL_RE.search(line)
        if m and _valid_email(m.group(1).lower()):
            return m.group(1).lower()
    return ""


def _valid_email(email: str) -> bool:
    low = email.lower()
    for bad in ("yourcompany", "yourdomain", "yourbusiness", "placeholder",
                "example.com", "@company.com", "@sitename", "@acme", "@your"):
        if bad in low:
            return False
    return True


def _key_value_to_row(lines: list[str]) -> pd.DataFrame | None:
    """Parse ONE invoice block (list of lines) into a schema'd row."""
    if not lines:
        return None

    customer_name, cust_line = _extract_customer(lines)
    email = _extract_email(lines, cust_line)

    inv_no = ""
    for line in lines:
        m = _INV_NO_RE.search(line)
        if m and _is_invoice_marker(line):
            inv_no = m.group(1).strip().strip("#").strip()
            break

    invoice_date = due_date = ""
    status_label = ""
    for line in lines:
        if not invoice_date:
            m = _INV_DATE_RE.search(line)
            if m:
                invoice_date = _clean_date(m.group(1))
        if not due_date:
            m = _DUE_RE.search(line)
            if m:
                due_date = _clean_date(m.group(1))
        if not status_label:
            m = _STATUS_RE.search(line)
            if m:
                status_label = m.group(1).strip().lower()

    totals = [_parse_money(m.group(1)) for m in _TOTAL_RE.finditer("\n".join(lines))]
    paid = [_parse_money(m.group(1)) for m in _PAID_RE.finditer("\n".join(lines))]

    status = status_label or "open"
    if due_date:
        try:
            import datetime as _dt
            due = _dt.date.fromisoformat(due_date)
            if not status_label and due < _dt.date.today():
                status = "overdue"
        except Exception:
            pass

    row = {
        "customer_name": customer_name or "Unknown customer",
        "invoice_number": inv_no or "UNKNOWN",
        "invoice_date": invoice_date,
        "due_date": due_date,
        "amount": round(totals[-1], 2) if totals else 0.0,
        "amount_paid": round(paid[-1], 2) if paid else 0.0,
        "status": status,
        "contact_email": email,
    }
    return pd.DataFrame([row])


def _key_value_rows(text: str) -> list[pd.DataFrame]:
    """Extract every invoice from a free-text document."""
    rows = []
    for lines in _blocks_from_text(text):
        r = _key_value_to_row(lines)
        if r is not None:
            rows.append(r)
    return rows


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def to_dataframe(candidates: dict) -> tuple[pd.DataFrame, list[str]]:
    """Return (schema'd DataFrame, warnings). Raises ValueError if unusable."""
    warnings: list[str] = []
    if candidates.get("error"):
        raise ValueError(candidates["error"])

    df = _collapse_to_schema(candidates.get("tables", []))
    if df is not None:
        missing = [k for k in SCHEMA if k not in df.columns]
        if missing:
            warnings.append(
                "Some columns weren't detected: " + ", ".join(missing)
                + " (they defaulted to empty / $0)."
            )
        return df, warnings

    if candidates.get("text"):
        rows = _key_value_rows(candidates["text"])
        if rows:
            out = pd.concat(rows, ignore_index=True)
            names = [r["customer_name"][0] for r in rows]
            if len(out) > 1:
                if len(set(names)) > 1:
                    warnings.append(
                        "File contains invoices for MULTIPLE companies ("
                        + ", ".join(names) + ") - they were split into separate customers."
                    )
                else:
                    warnings.append(
                        f"File contains {len(out)} invoices for a single customer - "
                        "they were grouped together."
                    )
            else:
                warnings.append(
                    "No table header was found, so this file was read as a single "
                    "invoice via text extraction. Check the row for accuracy."
                )
            return out, warnings

    raise ValueError(
        "Could not find invoice data in this file. Expected a table with "
        "columns like invoice number, date, due date, amount, amount paid, "
        "and status - or a recognizable invoice layout."
    )


def read_records(path: str) -> tuple[pd.DataFrame, list[str]]:
    """Full ingest pipeline for one file: load -> extract -> normalize."""
    from loaders import formats

    candidates = formats.extract(path)
    return to_dataframe(candidates)