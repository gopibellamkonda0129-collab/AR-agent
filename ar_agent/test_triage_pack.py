import ai_generator
import ar_engine
import normalize

df, _ = normalize.read_records("sample_data/invoice_pack_4.pdf")
invoices, _ = ar_engine.df_to_invoices(df, source="invoice_pack_4.pdf")
rows = ai_generator.build_triage(ar_engine.group_by_customer(invoices))

header = f"{'customer':<28}{'invoice':<10}{'outstanding':>12}{'days':>5} {'priority':<8} email"
print(header)
for r in rows:
    print(
        f"{r['customer_name']:<28}{'-':<10}{r['total_outstanding']:>12,.2f}"
        f"{r['days_overdue']:>5} {r['priority']:<8} {r['contact_email']}"
    )
print()

assert all(r["contact_email"] != "billing@yourcompany.com" for r in rows), "issuer email leaked"
assert all(r["total_outstanding"] > 0 for r in rows), "NaN/zero outstanding"
print("Sample draft email for #003 (Harbor Freight - 8 days overdue):")
print(next(r["draft_email"] for r in rows if "Harbor" in r["customer_name"]))