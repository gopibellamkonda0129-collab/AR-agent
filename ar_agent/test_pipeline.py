import ar_engine
import ai_generator

with open("sample_data/customers.csv", encoding="utf-8-sig") as f:
    contents = f.read()

invoices, warnings = ar_engine.parse_csv(contents)
groups = ar_engine.group_by_customer(invoices)
rows = ai_generator.build_triage(groups)

print(f"invoices parsed: {len(invoices)}, customers grouped: {len(groups)}, warnings: {len(warnings)}")
print()
for r in rows:
    print(
        f"{r['customer_name']:<18} ${r['total_outstanding']:>10,.2f}  "
        f"{r['days_overdue']:>3}d  {r['priority']:<7} {r['risk_level']:<8} | "
        f"{r['recommended_action'][:60]}"
    )
print()
print("--- ACTIONS FOR TOP PRIORITY CUSTOMER ---")
print(rows[0]["customer_name"], "|", rows[0]["reason"])
print(rows[0]["recommended_action"])
print()
print("--- SAMPLE DRAFT EMAIL ---")
print(rows[0]["draft_email"])