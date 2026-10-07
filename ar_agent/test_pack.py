import datetime as dt

import ai_generator
import ar_engine
import normalize

df, warns = normalize.read_records("sample_data/invoice_pack_4.pdf")
print("WARNINGS:")
for w in warns:
    print("  -", w)
print()

invoices, _ = ar_engine.df_to_invoices(df, source="invoice_pack_4.pdf")
today = dt.date.today()
print(f"{'customer':<26}{'invoice':<8}{'due':<12}{'amount':>11}{'days':>5}  email")
for i in invoices:
    print(
        f"{i.customer_name:<26}{i.invoice_number:<8}{i.due_date:<12}"
        f"{i.amount:>11,.2f}{i.days_overdue:>5}  {i.contact_email}"
    )

groups = ar_engine.group_by_customer(invoices)
print()
print("GROUPS:", len(groups))
for g in groups:
    print(
        f"  {g.name}  ${g.total_outstanding:,.2f}  overdue={g.max_days_overdue}d  {g.priority}"
    )

total = sum(i.amount for i in invoices)
print(f"GRAND TOTAL: ${total:,.2f}  (expected 19,649.95)")

ok = (
    len(groups) == 4
    and abs(total - 19649.95) < 0.01
    and all(i.contact_email != "billing@yourcompany.com" for i in invoices)
    and all(i.invoice_number != "UNKNOWN" for i in invoices)
    and sorted(i.contact_email for i in invoices)
    == sorted(
        [
            "billing@greenleaf-landscaping.com",
            "ap@techwavesolutions.com",
            "payables@harborfreight-logistics.com",
            "finance@sunrisebakery.cafe",
        ]
    )
    and all(i.due_date for i in invoices)
)
print()
print("CHECK:", "PASS" if ok else "FAIL")