import io
import os

from app import app

client = app.test_client()

# GET /
r = client.get("/")
print("GET / :", r.status_code)

# 1) empty submission
r = client.post("/analyze", data={}, content_type="multipart/form-data")
print("POST /analyze (no file):", r.status_code)

# 2) multi-file, mixed formats
files = {
    "files": [
        (io.BytesIO(open(os.path.join("sample_data", "customers.csv"), "rb").read()), "customers.csv"),
        (io.BytesIO(open(os.path.join("sample_data", "ledger_variant.xlsx"), "rb").read()), "ledger_variant.xlsx"),
        (io.BytesIO(open(os.path.join("sample_data", "invoice_single.pdf"), "rb").read()), "invoice_single.pdf"),
        (io.BytesIO(open(os.path.join("sample_data", "ledger_mix.docx"), "rb").read()), "ledger_mix.docx"),
    ]
}
r = client.post("/analyze", data=files, content_type="multipart/form-data")
print("POST /analyze (4 mixed files):", r.status_code)

body = r.get_data(as_text=True)
checks = {
    "Northwind Trading": "customer from csv rendered",
    "Omega Logistics": "customer from xlsx rendered",
    "Aspen Ridge Hotels": "customer from pdf rendered",
    "HIGHEST": "priority pills rendered",
}
for term, label in checks.items():
    assert term in body, f"missing: {term} ({label})"
print("  -> all 3 formats + triage rendered OK")

# 3) a garbage file -> should surface error gracefully
r = client.post(
    "/analyze",
    data={"files": (io.BytesIO(b"no useful data here at all"), "junk.pdf")},
    content_type="multipart/form-data",
)
print("POST /analyze (garbage pdf):", r.status_code)
assert "No usable invoice data" in r.get_data(as_text=True)

# 4) unsupported extension -> redirect back with flash
r = client.post(
    "/analyze",
    data={"files": (io.BytesIO(b"x"), "notes.exe")},
    content_type="multipart/form-data",
)
print("POST /analyze (unsupported ext):", r.status_code)
assert r.status_code == 200 and "unsupported format" in r.get_data(as_text=True)

# 5) download endpoints
import json as _json
row = {
    "customer_name": "X",
    "contact_email": "x@y.com",
    "total_outstanding": 100.0,
    "days_overdue": 5,
    "invoice_count": 1,
    "risk_level": "high",
    "priority": "HIGH",
    "score": 60,
    "reason": "late",
    "recommended_action": "call",
    "draft_email": "Subject: hi",
}
r = client.post("/download", data={"data": _json.dumps([row])})
assert r.status_code == 200 and r.data.startswith(b"customer_name")
r = client.post("/export", data={"data": _json.dumps([row])})
assert r.status_code == 200 and b"CUSTOMER: X" in r.data
print("download + export endpoints: OK")

print("ALL WEB TESTS PASSED")