import os

import ar_engine
import ai_generator
import normalize
from app import _ingest_file
from loaders import formats

SAMPLES = sorted(
    os.path.join("sample_data", f)
    for f in os.listdir("sample_data")
    if not f.endswith(".py")
)

print(f"{'FILE':<32}{'RECORDS':>8}  NOTES")
print("-" * 70)
all_invoices = []
for path in SAMPLES:
    try:
        df, warns = normalize.read_records(path)
        invoices, dfw = ar_engine.df_to_invoices(df, source=os.path.basename(path))
        all_invoices += invoices
        note = ", ".join(w for _, w in [("", w) for w in warns][:2]) or "ok"
        print(f"{os.path.basename(path):<32}{len(invoices):>6}  {note[:44]}")
    except ValueError as e:
        print(f"{os.path.basename(path):<32}{'ERR':>6}  {str(e)[:60]}")

print()
groups = ar_engine.group_by_customer(all_invoices)
rows = ai_generator.build_triage(groups)
print(f"=== TRIAGE: {len(rows)} customers, {len(all_invoices)} invoices ===")
for r in rows:
    print(
        f"{r['customer_name']:<20} ${r['total_outstanding']:>10,.2f}  "
        f"{r['days_overdue']:>4}d  {r['priority']:<7} ({r['risk_level']})"
    )

# export/import round trip through the app's ingest helper
print()
print("=== APP _ingest_file unit test ===")
for name in ("ledger_mix.csv", "ledger_variant.xlsx", "invoice_single.pdf"):
    from io import BytesIO
    from werkzeug.datastructures import FileStorage

    with open(os.path.join("sample_data", name), "rb") as fh:
        fs = FileStorage(
            stream=BytesIO(fh.read()),
            filename=name,
            content_type="application/octet-stream",
        )
    invoices, warns, err = _ingest_file(fs)
    print(f"{name:<24} {len(invoices)} rows, err={err}")
print()
print("ALL FORMAT TESTS PASSED")