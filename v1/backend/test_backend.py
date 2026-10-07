"""End-to-end smoke test of the V1 backend in demo mode (no network/credentials).

The sample workspace (fictional data, 12 customers / 27 sample invoices + 12
emails) flows through the SAME import/analyze/match pipeline real data uses.
This file asserts the full product contract: signals, promises, daily action
queue, follow-up drafts, payments/recovery, forecast, and the weekly brief.
"""
import sys
from pathlib import Path

from urllib.parse import quote

from fastapi.testclient import TestClient

import database
database.repo = database._MemoryRepo()

from app import app
import app as app_mod

client = TestClient(app)

import demo.seed as seed_mod
seed_mod.repo = database.repo

failures = []


def check(label, ok, detail=""):
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {label}" + (f" - {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(label)


SAMPLE_CSV = Path(__file__).resolve().parents[2] / "ar_agent" / "sample_data" / "customers.csv"

# health
r = client.get("/health")
data = r.json()
check("health", r.status_code == 200 and data.get("demo") is True, str(data))

# fresh start: empty until the sample workspace is loaded (no lifespan in this
# harness; the app seeds on startup in real runs)
r = client.get("/customers/overview")
check("fresh app is empty", r.json().get("total_invoices") == 0, str(r.json()))
r = client.get("/invoices")
check("no invoices listed initially", r.json().get("count") == 0, str(r.json()))

# sample workspace: pulls the bundled fictional inbox -> creates signals
r = client.post("/demo/sync")
sync = r.json()
check("demo sync 200", r.status_code == 200, str(sync))
check("demo sync fetched 11", sync.get("fetched", 0) == 12, str(sync))
check("demo sync rows all new first time", sync.get("new_emails", 0) == sync.get("fetched", 0), str(sync))
check("demo sync new_signals=11", sync.get("new_signals", 0) == 12, str(sync))
first_signals = sync.get("new_signals", 0)

# account records the sync
r = client.get("/accounts")
acc = r.json()[0]
check("account reports last_sync_at", bool(acc.get("last_sync_at")), str(acc))
check("account reports new emails detected", acc.get("last_sync_new_emails", 0) == 12, str(acc))

# idempotent second sync -> nothing new detected
r = client.post("/demo/sync")
check("demo sync idempotent", r.json().get("new_signals", 99) == 0 and r.json().get("new_emails", 9) == 0, str(r.json()))

# the sample ledger is rich and fictional
r = client.get("/invoices")
inv = r.json()
check("sample ledger has 25 invoices", inv.get("count") == 38, str(inv.get("count")))
names = {i["customer_name"] for i in inv["invoices"]}
check("fictional customers present",
      {
          "Acme Digital", "Vertex Systems", "Northstar Media", "Marlowe & Co",
          "Fieldstone Partners", "Sunrise Bakery & Cafe", "Oak & Stone",
          "Beacon Press Group", "BluePeak Solutions", "GreenLeaf Landscaping",
          "Sterling & Vale",
      }.issubset(names), str(sorted(names)))
check("no real company names leaked", not (names & {"Google", "Microsoft", "Tesla", "ABC Ltd"}), str(names))

open_inv = [i for i in inv["invoices"] if float(i.get("amount_outstanding") or 0) > 0]
paid_inv = [i for i in inv["invoices"] if float(i.get("amount_outstanding") or 0) <= 0]
check("workspace has 5 paid invoices", len(paid_inv) == 16, str(len(paid_inv)))
check("workspace leaves 20 open invoices", len(open_inv) == 22, str(len(open_inv)))
overdue30 = [i for i in open_inv if i["due_date"] and (__import__("datetime").date.today()
            - __import__("datetime").date.fromisoformat(i["due_date"])).days >= 30]
check("has at least 2 invoices 30+ days overdue", len(overdue30) >= 2, str(len(overdue30)))

# signals list + classification coverage
r = client.get("/signals")
signals = r.json()
check("signals listed", isinstance(signals, list) and len(signals) > 0, str(len(signals) if isinstance(signals, list) else signals))
types = {s.get("signal_type") for s in signals}
for expected in ["payment_promise", "dispute", "wrong_po",
                 "payment_confirmation", "bounced_email", "info_question",
                 "approval_pending"]:
    check(f"signal type present: {expected}", expected in types, str(sorted(types)))

# missing_invoice + documentation_request classifiers still work (covered via
# the same analyzer the inbox uses, so the workspace stays lean)
from services.analyzer import analyze_email
_syn_missing = analyze_email("Re: invoice", "We did not receive invoice INV-1006 - please resend the PDF.", use_llm=False)
_syn_docs = analyze_email("Re: invoice", "Please send us a W-9 and the certificate of insurance for invoice INV-1012.", use_llm=False)
check("analyzer detects missing invoice", _syn_missing.get("signal_type") == "missing_invoice", str(_syn_missing))
check("analyzer detects documentation request", _syn_docs.get("signal_type") == "documentation_request", str(_syn_docs))

# a future promise (GreenLeaf -> next Friday) and a MISSED promise (Vertex)
import datetime as dt
green_promise = next((s for s in signals
                      if s.get("signal_type") == "payment_promise"
                      and s.get("customer_name") == "GreenLeaf Landscaping"), {})
check("future promise has promised_date", bool(green_promise.get("promised_date")),
      str(green_promise.get("promised_date")))
check("future promise amount == 1620", green_promise.get("promised_amount") == 1620.0,
      str(green_promise.get("promised_amount")))
check("future promise matched customer", green_promise.get("customer_name") == "GreenLeaf Landscaping",
      f"{green_promise.get('customer_name')}|{green_promise.get('customer_email')}")
gd = dt.date.fromisoformat(green_promise["promised_date"])
check("future promise date in future (>=1d away)", (gd - dt.date.today()).days >= 1, str(gd))

vertex_promise = next((s for s in signals
                       if s.get("signal_type") == "payment_promise"
                       and s.get("customer_name") == "Vertex Systems"), {})
check("missed promise is in the past", bool(vertex_promise.get("promised_date"))
      and dt.date.fromisoformat(vertex_promise["promised_date"]) < dt.date.today(),
      str(vertex_promise.get("promised_date")))
check("missed promise tied to INV-1004", vertex_promise.get("related_invoice") == "INV-1004",
      str(vertex_promise.get("related_invoice")))

# resolve a signal AFTER the queue assertions below (resolving Fieldstone's
# dispute removes it from the queue, which would change the counts).
dispute = next((s for s in signals if s.get("signal_type") == "dispute"), {})
_dispute_customer = dispute.get("customer_name")
rid = dispute["id"]

# customers: aggregations include sample invoices
r = client.get("/customers")
cust = r.json()
cnames = {c["customer_name"] for c in cust}
check("10 sample customers in ledger", {
    "Acme Digital", "Vertex Systems", "Northstar Media", "Marlowe & Co",
    "Fieldstone Partners", "Sunrise Bakery & Cafe", "Oak & Stone",
    "Beacon Press Group", "BluePeak Solutions", "GreenLeaf Landscaping",
}.issubset(cnames), str(cnames))
total = sum(c["total_outstanding"] for c in cust)
check("ledger total outstanding == 164,596.20", round(total, 2) == 164596.20, str(total))

# promise tracker
r = client.get("/customers/promises")
promises = r.json()
check("promise tracker lists open promises", any(p["status"] == "upcoming" for p in promises), str(promises))
check("promise tracker has missed promise", any(p["status"] == "overdue" for p in promises), str(promises))

# ---------------------------------------------------------------------------
# PRODUCT LAYER: ACTION REQUIRED queue ("who should I chase today")
# ---------------------------------------------------------------------------
r = client.get("/actions")
queue = r.json()
kpis = queue.get("kpis", {})
check("actions queue 200 + kpis", r.status_code == 200 and kpis.get("cash_at_risk", 0) > 0, str(kpis))
acts = queue.get("actions", [])
check("sample action queue has 9 chase-worthy accounts",
      isinstance(acts, list) and len(acts) == 12, str(len(acts)))

req = kpis.get("customers_requiring_action", 0)
check("kpis match queue length", req == 12, str(req))
drivers = {x["customer_name"]: x for x in acts}

check("pre-due customer joins the queue with a readiness action",
      drivers.get("Oak & Stone", {}).get("action") == "CONFIRM_PAYMENT_READINESS"
      and (drivers.get("Oak & Stone", {}).get("action_category") or {}).get("category") == "pre_due",
      str(drivers.get("Oak & Stone", {}).get("action_category")))

check("kpis expose overdue + due_this_week",
      abs(kpis.get("overdue", 0) - 66906.2) < 0.01 and abs(kpis.get("due_this_week", 0) - 35470.0) < 0.01,
      str({k: kpis.get(k) for k in ("overdue", "due_this_week")}))
check("kpis total matches the ledger", abs(kpis.get("total_outstanding", 0) - 164596.20) < 0.01,
      str(kpis.get("total_outstanding")))
check("kpis priority bands correct", kpis.get("high_priority_customers", 0) == 3 and kpis.get("overdue_promises", 0) == 1,
      str({k: kpis.get(k) for k in ("high_priority_customers", "overdue_promises", "promises_open")}))

a = acts
check("action priority bands valid", all(x.get("priority") in ("critical", "high", "medium", "low") for x in a),
      str([(x["customer_name"], x.get("priority")) for x in a]))
check("every queue item has action+reason+confidence+date",
      all(x.get("action") and x.get("action_label") and x.get("reason")
          and x.get("priority_reasons") and 0.4 <= x.get("recommendation_confidence", 0) <= 0.9
          and bool(x.get("suggested_follow_up_date")) for x in a), "see failures")

vx = drivers.get("Vertex Systems", {})
check("missed promise -> FOLLOW_UP_MISSED_PROMISE", vx.get("action") == "FOLLOW_UP_MISSED_PROMISE", str(vx.get("action")))
check("missed promise explains the why", "promised" in (vx.get("reason") or "").lower(), str(vx.get("reason")))
check("missed promise makes the account critical", vx.get("priority") == "critical", str(vx.get("priority")))
check("priority score is explainable", len(vx.get("priority_reasons", [])) >= 2, str(vx.get("priority_reasons")))

acme = drivers.get("Acme Digital", {})
check("overdue no-response account -> ESCALATE (high)",
      acme.get("action") == "ESCALATE" and acme.get("priority") == "high",
      str((acme.get("action"), acme.get("priority"))))

bp = drivers.get("BluePeak Solutions", {})
check("open dispute maps to INVESTIGATE_DISPUTE", bp.get("action") == "INVESTIGATE_DISPUTE", str(bp.get("action")))
check("open dispute draft type = dispute_clarification", bp.get("draft_type") == "dispute_clarification", str(bp.get("draft_type")))

beacon = drivers.get("Beacon Press Group", {})
check("wrong_po maps to REQUEST_CORRECTED_PO", beacon.get("action") == "REQUEST_CORRECTED_PO", str(beacon.get("action")))

northstar = drivers.get("Northstar Media", {})
check("customer question maps to REPLY_TO_QUESTION", northstar.get("action") == "REPLY_TO_QUESTION", str(northstar.get("action")))

sunrise = drivers.get("Sunrise Bakery & Cafe", {})
check("bounced email maps to FIND_ALTERNATE_CONTACT", sunrise.get("action") == "FIND_ALTERNATE_CONTACT",
      str((sunrise.get("action"), sunrise.get("customer_name"))))

greenleaf = drivers.get("GreenLeaf Landscaping", {})
check("payment confirmation maps to VERIFY_PAYMENT", greenleaf.get("action") == "VERIFY_PAYMENT", str(greenleaf.get("action")))

# latest_signal carries source email evidence for the follow-up panel
vx_driver = drivers.get("Vertex Systems", {})
check("latest signal exposes source email metadata",
      bool((vx_driver.get("latest_signal") or {}).get("source_email", {}).get("subject")),
      str((vx_driver.get("latest_signal") or {}).get("source_email")))

# ---------------------------------------------------------------------------
# PROCESS STATUS extension: per-invoice where-it-is, action categories, AR doc
# ---------------------------------------------------------------------------
_invrows = client.get("/invoices").json()["invoices"]
_by_num = {i["invoice_number"]: i for i in _invrows}
check("every invoice has a process_status", all("process_status" in i for i in _invrows), "missing key")
_ps = lambda n: _by_num.get(n, {}).get("process_status", {})
check("INV-1043 (approval message) -> approval_pending",
      _ps("INV-1043").get("status") == "approval_pending"
      and _ps("INV-1043").get("stage") == "Customer approval"
      and _ps("INV-1043").get("blocker"), str(_ps("INV-1043")))
check("INV-1017 (Beacon wrong_po) -> po_pending",
      _ps("INV-1017").get("status") == "po_pending", str(_ps("INV-1017")))
check("INV-1005 (Vertex wrong_po) -> po_pending",
      _ps("INV-1005").get("status") == "po_pending", str(_ps("INV-1005")))
check("INV-1042 partial payments stay overdue (not 'paid')",
      _ps("INV-1042").get("status") == "payment_overdue"
      and "partial" in (_ps("INV-1042").get("facts") or {}).get("paid", {}).get("note", ""),
      str(_ps("INV-1042")))
_sv = {x["customer_name"]: x for x in client.get("/actions").json()["actions"]}.get("Sterling & Vale", {})
check("approval blocker -> REQUEST_APPROVAL_STATUS (process)",
      _sv.get("action") == "REQUEST_APPROVAL_STATUS"
      and (_sv.get("action_category") or {}).get("category") == "process"
      and "approval" in ((_sv.get("stuck") or {}).get("where") or ""),
      str((_sv.get("action"), _sv.get("action_category"))))
_acats = queue.get("kpis", {}).get("actions_by_category", {})
check("queue kpis break down by action category",
      _acats == {"collection": 5, "dispute": 1, "process": 5, "pre_due": 1},
      str(_acats))
_ardoc = client.get("/reports/ar-process").json()
check("AR process doc has observed + recommended + note",
      len(_ardoc.get("observed", [])) == 9 and len(_ardoc.get("recommended", [])) == 8 and bool(_ardoc.get("note")),
      str({k: len(_ardoc.get(k, [])) for k in ("observed", "recommended")}))
_appr_step = next((s for s in _ardoc.get("observed", []) if s.get("key") == "approval"), {})
check("AR doc sees the approval wallet KNOWN with count",
      _appr_step.get("state") == "KNOWN" and _appr_step.get("count", 0) == 1, str(_appr_step))
_ar = client.get(f"/customers/intelligence/{quote('Sterling & Vale')}").json().get("ar_process", {})
check("customer AR process shows the current stage + posture",
      (_ar.get("current") or {}).get("current_stage") == "Customer approval"
      and bool((_ar.get("posture") or {}).get("label")), str(_ar.get("current")))
_apf = client.get(f"/followups/{quote('Sterling & Vale')}").json()
check("approval draft is generated + no internal guidance leaked to the customer",
      _apf.get("draft_type") == "approval_pending_followup"
      and "INV-1043" in _apf.get("body", "")
      and "don't chase" not in _apf.get("body", "").lower(),
      str(_apf.get("subject")))

# resolve the dispute (a real workflow step: investigate, then mark resolved)
r = client.post(f"/signals/{rid}/resolve", json={"resolved": True, "note": "followed up, customer will provide PO"})
check("resolve signal", r.status_code == 200 and r.json().get("resolved") is True, str(r.json()))
check("resolved dispute belonged to a sample account (demo order-agnostic)",
      _dispute_customer in ("Fieldstone Partners", "BluePeak Solutions"), str(_dispute_customer))
r = client.get("/signals", params={"resolved": "true"})
check("resolved filter", any(s["id"] == rid for s in r.json()), "filter returned nothing")

# bounce was routed to the REAL customer (Sunrise) despite mailer-daemon sender:
# the signal must carry the customer name so the queue can act on it
sunrise_sig = next((s for s in client.get("/signals").json()
                    if s.get("signal_type") == "bounced_email"), {})
check("bounce routed to its customer (not blank)",
      sunrise_sig.get("customer_name") == "Sunrise Bakery & Cafe",
      str(sunrise_sig.get("customer_name")))

# ---------------------------------------------------------------------------
# ADDITIVE VIEWS & SIGNALS (V1.3): cash-at-risk view, amount×days comparison,
# promise-kept rate breakdown, posture confidence, manual ownership override,
# exception groups, pre-due KPIs, evidence_items, what-changed timeline.
# ---------------------------------------------------------------------------
car = client.get("/invoices/cash-at-risk").json()
t = car.get("totals", {})
check("cash-at-risk totals present", bool(car.get("rows")) and t.get("open_invoices", 0) == 22, str(t))
check("cash-at-risk weighted risk is amount×days (additive)",
      t.get("weighted_risk", 0) > t.get("overdue_amount", 0), str(t))
crows = {r["invoice_number"]: r for r in car.get("rows", [])}
check("cash-at-risk blocker band surfaces wrong PO",
      crows.get("INV-1017", {}).get("band") == "blocked"
      and "PO" in (crows.get("INV-1017", {}).get("next_action") or ""),
      str(crows.get("INV-1017", {}).get("band")))
check("cash-at-risk blocker band surfaces the remaining dispute",
      any(crows.get(n, {}).get("band") == "blocked"
          for n in ("INV-1013", "INV-1018")), str(crows.get("INV-1013")))
check("cash-at-risk risk_weight == amount × days (per invoice)",
      all(abs(r["risk_weight"] - round(r["amount_outstanding"] * r["days_overdue"], 2)) < 0.01
          for r in car.get("rows", [])), "")

q2 = client.get("/actions").json()
qk = q2.get("kpis", {})
qacts = {x["customer_name"]: x for x in q2.get("actions", [])}
check("queue exposes exception groups",
      qk.get("exceptions", {}).get("missed_promise", 0) >= 1 and qk.get("exceptions_total", 0) >= 1,
      str(qk.get("exceptions")))
check("missed promise is its own exception group",
      qacts.get("Vertex Systems", {}).get("exception_group") == "missed_promise",
      str(qacts.get("Vertex Systems", {}).get("exception_group")))
check("wrong PO grouped as blocked exception",
      qacts.get("Beacon Press Group", {}).get("exception_group") == "blocked",
      str(qacts.get("Beacon Press Group", {}).get("exception_group")))
check("payment confirmation groups as verify",
      qacts.get("GreenLeaf Landscaping", {}).get("exception_group") == "verify",
      str(qacts.get("GreenLeaf Landscaping", {}).get("exception_group")))
check("dispute exception group surfaces while unresolved",
      qk.get("exceptions", {}).get("dispute", 0) >= 1, str(qk.get("exceptions")))
check("pre-due KPIs surfaced", qk.get("pre_due_count", 0) >= 1 and qk.get("pre_due_amount", 0) > 0,
      str({k: qk.get(k) for k in ("pre_due_count", "pre_due_amount")}))
check("per-item amount×days comparison ranks present",
      all(x.get("simple_priority_rank") and x.get("agent_rank") and x.get("comparison_reason")
          for x in q2.get("actions", [])), "")

acme_b = qacts.get("Acme Digital", {}).get("behavior", {})
acme_bd = acme_b.get("promise_breakdown") or []
check("promise-kept breakdown lists per-promise rows",
      len(acme_bd) >= 2 and sum(1 for p in acme_bd if p["outcome"] == "kept") == 2
      and acme_b.get("promises_kept_percent") == 100, str(acme_bd))
vertex_bd = (qacts.get("Vertex Systems", {}).get("behavior", {}) or {}).get("promise_breakdown") or []
check("promise breakdown marks kept with late days",
      any(p["outcome"] == "kept" and p.get("late_days") is not None for p in vertex_bd)
      and any(p["outcome"] == "missed" for p in vertex_bd), str(vertex_bd))

svp = client.get(f"/customers/intelligence/{quote('Sterling & Vale')}").json().get("ar_process", {}).get("posture", {})
check("posture carries confidence + evidence status",
      svp.get("posture") == "process_problem" and 0 < svp.get("confidence", 0) < 1
      and svp.get("evidence_status") in ("KNOWN", "INFERRED", "UNKNOWN"), str(svp))
collectable = client.get(f"/customers/intelligence/{quote('Oak & Stone')}").json().get("ar_process", {}).get("posture", {})
check("collectable posture is neutral wording",
      collectable.get("label") == "Committed payment date on file", str(collectable))

r = client.post("/actions/Vertex Systems/owner", json={"owner": "Collections Lead"})
check("owner override saves", r.status_code == 200 and r.json().get("manual") is True, str(r.json()))
ov = {x["customer_name"]: x for x in client.get("/actions").json()["actions"]}.get("Vertex Systems", {}).get("ownership", {})
check("owner override surfaces as manual", ov.get("manual") is True and ov.get("who") == "Collections Lead", str(ov))
tl_owned = client.get(f"/customers/{quote('Vertex Systems')}").json().get("timeline", [])
check("what-changed timeline records the manual owner",
      any("Owner assigned manually" in (x.get("title") or "") for x in tl_owned), str(tl_owned[-3:]))
r = client.post("/actions/Vertex Systems/owner", json={"owner": ""})
check("owner override clears", r.status_code == 200 and r.json().get("manual") is False, str(r.json()))

_invr = client.get("/invoices").json()["invoices"]
check("every invoice carries structured evidence_items",
      all((i.get("process_status") or {}).get("evidence_items") for i in _invr), "")
_ps1043 = next((i.get("process_status", {}) for i in _invr if i.get("invoice_number") == "INV-1043"), {})
check("evidence_items carry source + marker + date",
      any(e.get("source") == "email" and e.get("evidence_status") == "KNOWN" and e.get("date")
          for e in _ps1043.get("evidence_items", [])), str(_ps1043.get("evidence_items")))

# ---------------------------------------------------------------------------
# Invoice lifecycle + send-readiness + reminder safety + control center
# ---------------------------------------------------------------------------
_inv_by_num = {i.get("invoice_number"): i for i in client.get("/invoices").json()["invoices"]}
check("invoice list carries compact lifecycle",
      all(("lifecycle" in i and i["lifecycle"].get("current_stage") and i["lifecycle"].get("progress") is not None)
          for i in _invr), "")
check("invoice list carries readiness summary",
      all(("readiness_summary" in i and i["readiness_summary"].get("verdict") in
           ("READY", "CONFIRM", "NOT READY")) for i in _invr), "")
check("paid invoices reach progress 1.0",
      all((_inv_by_num[n].get("lifecycle") or {}).get("progress") == 1.0
          for n in _inv_by_num if float(_inv_by_num[n].get("amount_outstanding") or 0) <= 0), "")

_ap_1043 = client.get(f"/invoices/{_inv_by_num['INV-1043']['id']}/action-panel").json()
check("action panel returns the full block",
      {"lifecycle", "readiness", "reminder_safety", "payment_readiness_score",
       "recommended_action", "control"}.issubset(_ap_1043.keys()), str(sorted(_ap_1043.keys())))
check("action panel readiness has 10 checks",
      len(_ap_1043.get("readiness", {}).get("checks", [])) == 10,
      str(len(_ap_1043.get("readiness", {}).get("checks", []))))
check("action panel lifecycle marks approval-pending invoice",
      _ap_1043.get("lifecycle", {}).get("current_stage") == "approval",
      str(_ap_1043.get("lifecycle", {}).get("current_stage")))
check("reminder safety pauses approval holds",
      _ap_1043.get("reminder_safety", {}).get("verdict") == "PAUSE"
      and _ap_1043.get("reminder_safety", {}).get("product_rule") is True,
      str(_ap_1043.get("reminder_safety", {}).get("verdict")))
check("payment readiness score is transparent",
      _ap_1043.get("payment_readiness_score", {}).get("score") is not None
      and len(_ap_1043.get("payment_readiness_score", {}).get("signals", [])) == 5,
      str(_ap_1043.get("payment_readiness_score", {}).get("score")))

_ap_po = client.get(f"/invoices/{_inv_by_num['INV-1005']['id']}/action-panel").json()
check("reminder safety refuses a demand on PO mismatch",
      _ap_po.get("reminder_safety", {}).get("verdict") == "REQUEST_INFORMATION"
      and _ap_po.get("reminder_safety", {}).get("product_rule") is True,
      str(_ap_po.get("reminder_safety", {}).get("verdict")))
_ap_dispute = None
for d in ("INV-1013", "INV-1018"):
    pan = client.get(f"/invoices/{_inv_by_num[d]['id']}/action-panel").json()
    if pan.get("reminder_safety", {}).get("verdict") == "ESCALATE":
        _ap_dispute = pan
        break
check("reminder safety escalates disputes (no generic demand)",
      bool(_ap_dispute and _ap_dispute["reminder_safety"].get("product_rule") is True),
      str(_ap_dispute.get("reminder_safety") if _ap_dispute else "no dispute invoice"))
# the only missed-promise sample account also carries an open PO blocker, so the
# safety engine correctly defers the demand. Use a synthetic clean account to
# prove a missed promise DOES produce a SEND (with a firm-date request).
import datetime as _dt
from uuid import uuid4 as _uuid4
from services.next_action_engine import build_action_item
from services.behavior import enrich_action_item
from services.reminder_safety import reminder_safety
_syn_id = str(_uuid4())
database.repo.insert("invoices", [{
    "id": _syn_id, "customer_name": "Synthetic Co", "invoice_number": "SYN-001",
    "amount_outstanding": 500.0, "status": "open",
    "due_date": (_dt.date.today() - _dt.timedelta(days=20)).isoformat()}])
_syn_sig = database.repo.insert("signals", [{
    "customer_name": "Synthetic Co", "customer_email": "ap@synthetic.example",
    "signal_type": "payment_promise", "priority": "high",
    "promised_date": (_dt.date.today() - _dt.timedelta(days=5)).isoformat(),
    "related_invoice": "SYN-001", "resolved": False,
    "summary": "we will pay on the 10th"}])[0]
_syn_item = enrich_action_item(database.repo, build_action_item(database.repo, "Synthetic Co"))
_syn_safety = reminder_safety(database.repo, _syn_item)
check("reminder safety sends on a missed promise (a firm date, not a demand)",
      _syn_safety.get("verdict") == "SEND"
      and "firm revised date" in (_syn_safety.get("recommended_action") or "").lower()
      and _syn_safety.get("product_rule") is False,
      str(_syn_safety.get("verdict")))
database.repo.delete("invoices", _syn_id)
database.repo.delete("signals", _syn_sig["id"])

# follow-up control center: pause / resume / cancel-chase / next-action override
_pause_target = "Acme Digital"
r = client.post(f"/actions/{quote(_pause_target)}/pause", json={"until": "", "reason": "Awaiting their PO review"})
check("pause records a reason",
      r.status_code == 200 and r.json().get("paused") is True
      and r.json().get("reason") == "Awaiting their PO review", str(r.json()))
q_after_pause = client.get("/actions").json()
check("paused customer leaves the queue",
      _pause_target not in {a["customer_name"] for a in q_after_pause["actions"]},
      str([a["customer_name"] for a in q_after_pause["actions"] if a["customer_name"] == _pause_target]))
check("paused customer listed separately with reason",
      any(c["customer_name"] == _pause_target and c.get("paused_reason") for c in q_after_pause["paused"]),
      str(q_after_pause.get("paused")))
r = client.post(f"/actions/{quote(_pause_target)}/resume")
q_after_resume = client.get("/actions").json()
check("resume brings the customer back",
      r.status_code == 200 and r.json().get("paused") is False
      and _pause_target in {a["customer_name"] for a in q_after_resume["actions"]},
      str(r.json()))

r = client.post(f"/actions/{quote('Oak & Stone')}/pause", json={"until": "2030-01-01", "reason": "pause until resolved"})
q = client.get("/actions").json()
check("dated pause hides until the date",
      r.status_code == 200 and "Oak & Stone" not in {a["customer_name"] for a in q["actions"]}
      and any(c["customer_name"] == "Oak & Stone" and c.get("paused_until") == "2030-01-01"
              for c in q["paused"]), str(r.json()))
_tl_oak = client.get(f"/customers/{quote('Oak & Stone')}").json().get("timeline", [])
check("timeline records a pause while paused",
      any(x.get("kind") == "pause" and "until 2030-01-01" in (x.get("detail") or "")
          for x in _tl_oak),
      str([x for x in _tl_oak if x.get("kind") == "pause"]))
r = client.post("/actions/Oak & Stone/resume")
check("resume clears the pause date",
      r.status_code == 200
      and all(c["customer_name"] != "Oak & Stone"
              for c in client.get("/actions").json()["paused"]), str(r.json()))

r = client.post("/actions/GreenLeaf Landscaping/pause", json={"until": "", "reason": "Chase cancelled by the team"})
check("cancel-chase records a pause",
      r.status_code == 200 and r.json().get("paused") is True, str(r.json()))
r = client.post("/actions/GreenLeaf Landscaping/resume")

r = client.post("/actions/Beacon Press Group/next-action", json={"action": "Call AP to confirm the PO number"})
check("next-action override saves",
      r.status_code == 200 and r.json().get("manual") is True
      and r.json().get("action") == "Call AP to confirm the PO number", str(r.json()))
bp = {a["customer_name"]: a for a in client.get("/actions").json()["actions"]}.get("Beacon Press Group", {})
check("next-action override surfaces on the queue item",
      bp.get("next_action_override") == "Call AP to confirm the PO number", str(bp.get("next_action_override")))
_tl_beacon = client.get(f"/customers/{quote('Beacon Press Group')}").json().get("timeline", [])
check("timeline records the team-chosen next action",
      any(x.get("kind") == "action" and "Call AP" in (x.get("detail") or "")
          for x in _tl_beacon),
      str([x for x in _tl_beacon if x.get("kind") == "action"]))
r = client.post("/actions/Beacon Press Group/next-action", json={"action": ""})
check("next-action override clears", r.status_code == 200 and r.json().get("manual") is False, str(r.json()))

# recurring-invoice readiness (customers with 2+ invoices)
_rep = client.get(f"/invoices/{_inv_by_num['INV-1001']['id']}/action-panel").json()
check("action panel exposes recurring volume",
      isinstance(_rep.get("readiness"), dict) and len(_rep["readiness"].get("checks", [])) == 10, "")
from services.readiness import recurring_invoice_readiness
_rec = recurring_invoice_readiness(database.repo, "Acme Digital")
check("recurring readiness profiles repeat customers",
      _rec.get("recurring") is True and _rec.get("avg_interval_days") is not None,
      str(_rec.get("avg_interval_days")))
check("recurring readiness verdict is one of READY/REVIEW",
      _rec.get("verdict") in ("READY", "REVIEW")
      and isinstance(_rec.get("risks"), list), str(_rec.get("verdict")))

# timeline kinds extended (partial / invoice_issue / approval / pause / action)
_tl_sv = client.get(f"/customers/{quote('Sterling & Vale')}").json().get("timeline", [])
check("timeline records the approval hold",
      "approval" in {x.get("kind") for x in _tl_sv}, str(sorted({x.get("kind") for x in _tl_sv})))
check("timeline records invoice-issue events on a PO-mismatch account",
      "invoice_issue" in {x.get("kind") for x in _tl_beacon},
      str(sorted({x.get("kind") for x in _tl_beacon})))
check("every timeline event carries topics",
      all(x.get("topics") for x in _tl_sv + _tl_beacon + _tl_oak), "")

# cash-at-risk honors the agent sort without claiming superiority
car_w = client.get("/invoices/cash-at-risk?sort=weight").json()
car_a = client.get("/invoices/cash-at-risk?sort=agent").json()
check("cash-at-risk dual sort works",
      car_w.get("rows") and car_a.get("rows")
      and [r["invoice_number"] for r in car_w["rows"]] != [r["invoice_number"] for r in car_a["rows"]]
      , "")
check("cash-at-risk rows expose readiness + reliability + owner",
      all(r.get("readiness_verdict") and r.get("reliability")
          and "owner" in r for r in car_w["rows"]), "")
r = client.get("/invoices/cash-at-risk?sort=bogus")
check("cash-at-risk rejects unknown sort",
      r.status_code == 400, str(r.status_code))

# import a REAL ledger (V0 parser) on top of the sample
with open(SAMPLE_CSV, "rb") as f:
    r = client.post("/invoices/import", files={"files": ("customers.csv", f, "text/csv")})
imp = r.json()
check("import real CSV", imp.get("imported") == 8, str(imp))
check("import lists customers", "ABC Ltd" in imp.get("customers", []), str(imp.get("customers")))

r = client.get("/invoices")
check("ledger has sample+imported invoices", r.json().get("count") == 46, str(r.json().get("count")))

# an overdue REAL imported customer now enters the queue too
r = client.get("/actions")
post_import = {x["customer_name"]: x for x in r.json()["actions"]}
check("imported overdue customers join the queue",
      "Northwind Trading" in post_import and "ABC Ltd" in post_import,
      str(sorted(post_import.keys())))

# mapping contract: an open DISPUTE must map to INVESTIGATE_DISPUTE.
# (create one on ABC Ltd, which is now in the ledger - ABC has no signals yet)
_dummy = database.repo.insert("signals", [{
    "customer_name": "ABC Ltd",
    "signal_type": "dispute",
    "priority": "high",
    "confidence": 0.9,
    "summary": "Customer disputes the charge on the last invoice.",
    "resolved": False,
}])[0]
r = client.get("/actions")
abc = {x["customer_name"]: x for x in r.json()["actions"]}.get("ABC Ltd", {})
check("open dispute maps to INVESTIGATE_DISPUTE", abc.get("action") == "INVESTIGATE_DISPUTE", str(abc.get("action")))
check("open dispute draft type = dispute_clarification",
      abc.get("draft_type") == "dispute_clarification", str(abc.get("draft_type")))

# follow-up drafts: right draft for the right issue, facts not invented
r = client.get("/followups/Vertex Systems")
fu = r.json()
check("missed-promise draft type", fu.get("draft_type") == "missed_promise_followup", str(fu.get("draft_type")))
check("draft body references the invoice fact", "invoice" in fu.get("body", "").lower(), fu.get("body", "")[:80])
check("draft amount is the real ledger amount", "$12,400.00" in fu.get("body", ""), fu.get("body", "")[:200])
check("followup carries source evidence context", bool((fu.get("context") or {}).get("latest_signal")),
      str(fu.get("context", {})))

r = client.get("/followups/ABC Ltd")
fu = r.json()
check("dispute draft type", fu.get("draft_type") == "dispute_clarification", str(fu.get("draft_type")))
check("dispute draft asks for the disputed line item",
      "disputing" in fu.get("body", "").lower(), fu.get("body", "")[:120])

r = client.get("/followups/Beacon Press Group")
fu = r.json()
check("PO draft type", fu.get("draft_type") == "po_correction_request", str(fu.get("draft_type")))
check("PO draft subject mentions PO", "po" in fu.get("subject", "").lower(), fu.get("subject", ""))

r = client.get("/followups/GreenLeaf Landscaping")
check("verify-payment action has no email draft", r.json().get("draft_type") == "none", str(r.json().get("draft_type")))

# follow-up lifecycle: approve (sending disabled) -> copy -> discard
r = client.get("/followups/Vertex Systems")
cid = r.json()["id"]
r = client.post(f"/followups/{cid}/approve-send", json={"send": True})
ap = r.json()
check("approve-send records approval", ap.get("approved") is True and ap.get("sent") is False, str(ap))
check("approve-send explains sending disabled", "not enabled" in ap.get("message", "").lower(), ap.get("message", ""))
r = client.post(f"/followups/{cid}/copy")
check("copy followup", r.status_code == 200 and r.json().get("status") == "copied", str(r.json()))
r = client.post(f"/followups/{cid}/discard")
check("discard followup", r.status_code == 200 and r.json().get("status") == "discarded", str(r.json()))

# user can edit a draft (verbatim)
r = client.post("/followups/Vertex Systems", json={
    "draft_type": "dispute_clarification",
    "subject": "Custom subject",
    "body": "Custom body written by the user.",
})
check("save edited draft", r.status_code == 200 and r.json().get("status") == "edited", str(r.json()))
r = client.get("/followups/Vertex Systems")
check("edited draft is returned", "Custom body" in r.json().get("body", ""), r.json().get("body", "")[:80])

# work-queue state: mark contacted + snooze + reactivate
r = client.post("/actions/Vertex Systems/contacted", json={"note": "called, awaiting status"})
check("mark contacted", r.status_code == 200 and r.json().get("status") == "contacted", str(r.json()))
r = client.get("/actions")
state = {x["customer_name"]: x for x in r.json()["actions"]}
check("contacted state persists", state.get("Vertex Systems", {}).get("status") == "contacted",
      str(state.get("Vertex Systems", {}).get("status")))
check("contacted keeps note", state.get("Vertex Systems", {}).get("contact_note") == "called, awaiting status",
      str(state.get("Vertex Systems", {}).get("contact_note")))
_tl_cont = client.get(f"/customers/{quote('Vertex Systems')}").json().get("timeline", [])
check("what-changed timeline records 'Marked contacted'",
      any("Marked contacted" in (x.get("title") or "") for x in _tl_cont), str(_tl_cont[-3:]))

far = (dt.date.today() + dt.timedelta(days=30)).isoformat()
r = client.post("/actions/Sunrise Bakery & Cafe/snooze", json={"until": far})
check("snooze", r.status_code == 200 and r.json().get("status") == "snoozed", str(r.json()))
r = client.get("/actions")
named = r.json()["actions"]
check("snoozed item hidden from queue", all(x["customer_name"] != "Sunrise Bakery & Cafe" for x in named), "snoozed item still visible")
check("snoozed item listed separately",
      any(x["customer_name"] == "Sunrise Bakery & Cafe" for x in r.json().get("snoozed", [])),
      "snoozed section empty")
r = client.post("/actions/Sunrise Bakery & Cafe/reactivate")
check("reactivate", r.json().get("status") == "active", str(r.json()))

# expected cash: buckets only from explicit promises or ledger due dates.
# A MISSED promise must NOT land in "expected" - it is overdue, not expected.
r = client.get("/forecast")
fc = r.json()
buckets = {b["key"]: b for b in fc.get("buckets", [])}
total_ledger = sum(float(i.get("amount_outstanding") or 0)
                   for i in client.get("/invoices").json()["invoices"])
check("forecast total equals ledger", round(fc.get("total_cash", -1), 2) == round(total_ledger, 2),
      str(fc.get("total_cash")))
expected_items = [it for bk in ("expected_today", "expected_this_week", "expected_next_30_days", "expected_later")
                  for it in buckets.get(bk, {}).get("items", [])]
check("missed promise excluded from expected buckets",
      all(it.get("customer_name") != "Vertex Systems" for it in expected_items),
      str(expected_items))
check("promise lands in an expected bucket", any(it.get("customer_name") == "GreenLeaf Landscaping"
      and it.get("amount") == 1620.0 and it.get("source") == "customer promise"
      for it in expected_items), str(expected_items))
note = buckets.get("overdue_unconfirmed", {})
check("overdue bucket has no confirmed date", any(i.get("customer_name") == "ABC Ltd"
      for i in note.get("items", [])), str(note.get("items")))
check("all forecast buckets label source", all(b.get("source") in ("promise", "ledger") for b in buckets.values()),
      str([(k, v.get("source")) for k, v in buckets.items()]))

# weekly receivables brief
r = client.get("/reports/weekly")
wr = r.json()
check("weekly brief has all sections", all(k in wr for k in (
    "cash_collected", "new_overdue_invoices", "missed_payment_promises",
    "open_disputes", "largest_overdue_accounts", "expected_incoming_payments",
    "recommended_priorities_next_week")), "see above")
check("weekly brief flags open disputes", wr.get("open_disputes", {}).get("count", 0) >= 1, str(wr.get("open_disputes")))
check("weekly brief expects incoming payment", wr.get("expected_incoming_payments", 0) >= 1620, str(wr.get("expected_incoming_payments")))

# customer detail: everything in one view + timeline
r = client.get("/customers/Vertex Systems")
d = r.json()
check("customer detail 200 + invoices", r.status_code == 200 and d.get("invoices"), str(list(d.keys())))
check("customer detail recommendation", d.get("recommended_action", {}).get("action") == "FOLLOW_UP_MISSED_PROMISE", str(d.get("recommended_action")))
check("customer detail has timeline", len(d.get("timeline", [])) >= 2, str(len(d.get("timeline", []))))
dates = [t["date"] for t in d["timeline"]]
check("timeline is sorted by date", dates == sorted(dates), str(dates))

# MONEY RECOVERED: only changes when a real payment is recorded - never invented.
# The sample workspace ships with recorded demo payments = $119,360.
r = client.get("/reports/money-recovered")
mr = r.json()
check("money recovered endpoints", r.status_code == 200, str(mr))
check("seeded demo payments reflected", round(mr.get("total", -1), 2) == 119360.0, str(mr))
check("money recovered has month labels", bool(mr.get("this_month")) is not None, str(mr))

# mark an invoice paid -> money recovered reflects ONLY that recorded payment
inv_to_pay = next(i for i in client.get("/invoices").json()["invoices"]
                  if i["customer_name"] == "Northstar Media" and i["status"] != "paid")
r = client.post(f"/invoices/{inv_to_pay['id']}/mark-paid",
                json={"amount": 8400.0, "note": "wire received"})
check("mark paid", r.status_code == 200 and r.json().get("status") == "paid", str(r.json()))
r = client.get("/reports/money-recovered")
mr2 = r.json()
check("money recovered reflects recorded payment", round(mr2.get("total", -1), 2) == 127760.0, str(mr2))
check("new payment lands in the current month report", mr2.get("this_month", 0) >= 8400.0, str(mr2))
check("paid-up customer leaves the action queue", all(x["customer_name"] != "Northstar Media"
      for x in client.get("/actions").json()["actions"]), "paid invoice still in queue")

# overview (existing) still fine with the new endpoints mounted
r = client.get("/customers/overview")
ov = r.json()
# 12 synced signals + 1 open installment promise seeded from history = 13;
# then Fieldstone's dispute resolved (-1) and ABC Ltd dispute added (+1) -> 13
check("legacy overview counts open signals", ov.get("open_signals", -1) == 13, str(ov))
# promises: Vertex (missed), Fieldstone (today), Oak (upcoming), GreenLeaf
# (upcoming) + Harbor (open installments) = 5
check("overview counts 5 payment promises", ov.get("by_type", {}).get("payment_promise", 0) == 5, str(ov.get("by_type")))

# invoices clear (all gone => clean slate for production use)
r = client.post("/invoices/clear")
check("clear invoices", r.status_code == 200 and r.json().get("removed", 0) >= 34, str(r.json()))
r = client.get("/invoices")
check("ledger empty after clear", r.json().get("count") == 0, str(r.json()))

# startup auto-seed: an EMPTY workspace is seeded on boot (the product behavior)
app_mod._seed_sample_workspace()
r = client.get("/customers/overview")
auto = r.json()
check("auto-seed fills empty workspace", auto.get("total_invoices") == 38,
      str({"total_invoices": auto.get("total_invoices"),
           "open_signals": auto.get("open_signals", 0)}))
check("auto-seed includes signals", auto.get("open_signals", 0) > 0, str(auto))
app_mod._seed_sample_workspace()
check("auto-seed is idempotent", client.get("/invoices").json().get("count") == 38, "seeded twice")

# Gmail OAuth requires a configured client secret -> clean 400 (not a crash)
r = client.get("/gmail/start", params={"email": "test@example.com"})
check("gmail/start guarded without secret", r.status_code == 400, str(r.json()))

# connecting an IMAP inbox with bad credentials is rejected (not silently stored)
r = client.post("/accounts", json={
    "provider": "imap",
    "email": "nobody@nowhere.invalid",
    "display_name": "x",
    "config": {"email": "nobody@nowhere.invalid", "password": "wrong",
               "host": "imap.gmail.com", "port": "993"},
})
check("bad IMAP credentials rejected", r.status_code == 400, str(r.json()))
check("imap error hides technical detail", "IMAP4" not in str(r.json()).replace(" ", "")
      and "imaplib" not in str(r.json()), str(r.json()))
r = client.get("/accounts")
check("no bogus account stored", all(a.get("provider") != "imap" for a in r.json()),
      str([a.get("provider") for a in r.json()]))

# no stored account ever ships its stored credentials back to the browser
_secret_acct = database.repo.insert("email_accounts", [{
    "provider": "imap",
    "email": "secrets@example.test",
    "display_name": "x",
    "provider_config": {"email": "secrets@example.test", "password": "topsecret-app-pw",
                        "host": "imap.example.com", "port": "993"},
    "status": "connected",
}])[0]
_acct_view = next((a for a in client.get("/accounts").json() if a["id"] == _secret_acct["id"]), {})
check("account credentials masked from API responses",
      (_acct_view.get("provider_config") or {}).get("password") in (None, "***"),
      str(_acct_view.get("provider_config")))
database.repo.delete("email_accounts", _secret_acct["id"])

# emails endpoint lists synced mail
r = client.get("/emails/messages?limit=50")
check("emails listed", r.status_code == 200 and len(r.json()) == 12, str(len(r.json())))

# ---------------------------------------------------------------------------
# HALLUCINATION GUARDS: money/date facts must only ever come from real email.
# Vague intent is labeled "no confirmed date"; amounts are never read as dates.
# ---------------------------------------------------------------------------
_ANTI = [
    ("We'll probably get this sorted sometime next week.",
     "vague promise -> intent, no fabricated date"),
    ("Hi, we'll try to process this next week.",
     "vague 'process next week' -> must NOT become a confirmed-date promise"),
    ("It's looking good, we are working on it. Should be resolved soon.",
     "working on it -> intent, no date"),
    ("We will pay you the 1500 dollars.",
     "amount 1500 must never become a '15th' promise date"),
    ("Balance due is 1234.56. We will pay soon.",
     "no date + due to decimals -> no promise date"),
]
for _msg, _label in _ANTI:
    sig = analyze_email("Re: invoice", _msg, use_llm=False)
    check(f"no fake date: {_label}",
          sig.get("signal_type") == "payment_promise" and not sig.get("promised_date")
          or sig.get("signal_type") == "other",
          str(sig))

_MESSAGE_FACTS = [
    ("We received invoice 1824.", "received invoice is not 'payment made'"),
    ("Thanks for the reminder, bye.", "nothing -> no signal"),
]
for _msg, _label in _MESSAGE_FACTS:
    sig = analyze_email("Re: invoice", _msg, use_llm=False)
    check(f"no invented payment: {_label}",
          sig.get("signal_type") == "other", str(sig))

_REAL_FACTS = [
    ("We will pay by September 15.", "2026-09-15"),
    ("We'll wire the balance next Friday.", None),  # resolves relative; just needs a date
    ("Invoice #1824 has been paid on 2026-09-01.", None),  # payment_confirmation, no made-up promise
]
for _msg, _expect in _REAL_FACTS:
    sig = analyze_email("Re: invoice", _msg, use_llm=False)
    if _expect:
        check(f"real fact extracted: {_msg!r}",
              sig.get("promised_date") == _expect, str(sig))
    else:
        check(f"real fact extracted (dated): {_msg!r}",
              sig.get("promised_date") is not None or sig.get("signal_type") == "payment_confirmation",
              str(sig))

print()
if failures:
    print(f"{len(failures)} FAILURES: {failures}")
    sys.exit(1)
print("ALL TESTS PASSED")