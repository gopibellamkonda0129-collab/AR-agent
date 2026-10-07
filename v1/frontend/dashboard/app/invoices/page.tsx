"use client";

import { useMemo, useRef, useState } from "react";
import { clearInvoices, fetchInvoices, importInvoices, markInvoicePaid, type Invoice, type InvoiceImportResult } from "../../lib/api";
import { FilterChips, EvidenceDrawer, InvoiceActionPanelModal, Kpi, LifecycleProgress, Modal, PageTitle, ProcessStatusChip, ReadinessSummaryChip, Spinner, StatusPill, fmtDate, money, usePolling } from "../../lib/components";
import { CalendarClock, FileText, X } from "../../lib/icons";

type FilterKey = "all" | "paid" | "overdue" | "duesoon" | "open";

export default function InvoicesPage() {
  const list = usePolling(fetchInvoices, 30000);
  const fileRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const [res, setRes] = useState<InvoiceImportResult | null>(null);
  const [paying, setPaying] = useState<Invoice | null>(null);
  const [payAmt, setPayAmt] = useState("");
  const [payNote, setPayNote] = useState("");
  const [openInv, setOpenInv] = useState<Invoice | null>(null);
  const [evidenceInv, setEvidenceInv] = useState<Invoice | null>(null);
  const [panelInv, setPanelInv] = useState<Invoice | null>(null);
  const [filter, setFilter] = useState<FilterKey>("all");

  const onFiles = async (files: FileList | null) => {
    if (!files?.length) return;
    setBusy(true);
    setMsg(null);
    setRes(null);
    try {
      const r = await importInvoices(Array.from(files));
      setRes(r);
      setMsg({ kind: "ok", text: `${r.imported} invoice row${r.imported === 1 ? "" : "s"} imported (${r.files} file${r.files === 1 ? "" : "s"}).` });
      list.reload();
    } catch (e) {
      setMsg({ kind: "err", text: String(e) });
    } finally {
      setBusy(false);
    }
  };

  const onClear = async () => {
    if (!window.confirm("Delete ALL invoices in this workspace? This is not undoable.")) return;
    setBusy(true);
    try {
      await clearInvoices();
      list.reload();
    } catch (e) {
      setMsg({ kind: "err", text: String(e) });
    } finally {
      setBusy(false);
    }
  };

  const confirmPaid = async () => {
    if (!paying) return;
    const amount = parseFloat(payAmt);
    if (Number.isNaN(amount) || amount <= 0) {
      setMsg({ kind: "err", text: "Enter a valid payment amount." });
      return;
    }
    setBusy(true);
    setMsg(null);
    try {
      await markInvoicePaid(paying.id, { amount, note: payNote || undefined });
      setMsg({ kind: "ok", text: `${money(amount)} recorded against ${paying.invoice_number}.` });
      setPaying(null);
      setPayAmt("");
      setPayNote("");
      list.reload();
    } catch (e) {
      setMsg({ kind: "err", text: String(e) });
    } finally {
      setBusy(false);
    }
  };

  const all = list.data?.invoices ?? [];
  const counts = useMemo(
    () => ({
      all: all.length,
      paid: all.filter((i) => i.status.toLowerCase() === "paid").length,
      overdue: all.filter((i) => i.status.toLowerCase() === "overdue").length,
      duesoon: all.filter((i) => {
        const s = i.status.toLowerCase();
        if (s === "paid" || s === "overdue") return false;
        if (!i.due_date) return false;
        return Math.ceil((new Date(i.due_date).getTime() - Date.now()) / 86400000) <= 7;
      }).length,
      open: all.filter((i) => i.status.toLowerCase() !== "paid").length,
    }),
    [all]
  );

  const filtered = useMemo(() => {
    if (filter === "all") return all;
    if (filter === "paid") return all.filter((i) => i.status.toLowerCase() === "paid");
    if (filter === "overdue") return all.filter((i) => i.status.toLowerCase() === "overdue");
    if (filter === "open") return all.filter((i) => i.status.toLowerCase() !== "paid");
    return all.filter((i) => {
      const s = i.status.toLowerCase();
      if (s === "paid" || s === "overdue" || !i.due_date) return false;
      return Math.ceil((new Date(i.due_date).getTime() - Date.now()) / 86400000) <= 7;
    });
  }, [all, filter]);

  const chips: { key: FilterKey; label: string; count: number; active: boolean; onClick: () => void; tone?: string }[] = [
    { key: "all", label: "All", count: counts.all, active: filter === "all", onClick: () => setFilter("all") },
    { key: "overdue", label: "Overdue", count: counts.overdue, active: filter === "overdue", onClick: () => setFilter("overdue"), tone: "var(--red)" },
    { key: "duesoon", label: "Due soon", count: counts.duesoon, active: filter === "duesoon", onClick: () => setFilter("duesoon"), tone: "var(--amber)" },
    { key: "open", label: "Open", count: counts.open, active: filter === "open", onClick: () => setFilter("open"), tone: "var(--info)" },
    { key: "paid", label: "Paid", count: counts.paid, active: filter === "paid", onClick: () => setFilter("paid"), tone: "var(--green)" },
  ];

  return (
    <div className="page-body">
      <PageTitle title="Invoice ledger" sub="Your source of truth for what's outstanding. Import from CSV or Excel — the AI reads due dates and amounts from it." eyebrow="Ledger" />

      <section className="kpis">
        <Kpi label="Invoices" value={String(list.data?.count ?? 0)} sub="rows in the ledger" />
        <Kpi label="Outstanding" value={money(list.data?.total_outstanding)} tone="amber" sub="sum of open balances" />
        <Kpi label="Overdue" value={String(counts.overdue)} tone="red" sub="past due date" />
        <Kpi label="Paid" value={String(counts.paid)} tone="green" sub="settled to zero" />
      </section>

      {msg && <div className={`banner ${msg.kind === "err" ? "err" : ""}`}>{msg.text}</div>}

      {res && res.warnings?.length > 0 && (
        <div className="banner import-actions">
          {res.warnings.map((w, i) => (
            <span key={i}>{w}</span>
          ))}
        </div>
      )}

      <div className="card">
        <div className="hd-inline">
          <div>
            <h2>
              <FileText size={15} /> Import invoices
            </h2>
            <p className="muted" style={{ margin: "2px 0 0" }}>
              CSV or Excel (.xlsx). One row per invoice with customer name, invoice number, due date, and amount outstanding.
            </p>
          </div>
          <div className="row-btns">
            <input
              ref={fileRef}
              type="file"
              accept=".csv,.xlsx"
              multiple
              hidden
              onChange={(e) => onFiles(e.target.files)}
            />
            <button className="btn b-pri" disabled={busy} onClick={() => fileRef.current?.click()}>
              {busy ? <Spinner /> : "Choose files…"}
            </button>
            <button className="btn ghost" disabled={busy} onClick={onClear}>
              Clear all
            </button>
          </div>
        </div>
      </div>

      <div className="card">
        <div className="hd-inline">
          <h2>
            Invoices
            <span className="count">{list.data?.count ?? 0}</span>
          </h2>
          <FilterChips items={chips} />
        </div>
        {list.data && list.data.invoices.length === 0 ? (
          <div className="empty-hint">
            <b>No invoices yet.</b>
            <div className="muted">Import your ledger above. Everything downstream (promises, action queue, forecast) depends on this.</div>
          </div>
        ) : filtered.length === 0 ? (
          <div className="empty-hint">
            <b>Nothing in this view.</b>
            <div className="muted">Try another filter.</div>
          </div>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Invoice</th>
                  <th>Customer</th>
                  <th>Due date</th>
                  <th>Status</th>
                  <th>Process</th>
                  <th>Readiness</th>
                  <th className="num">Outstanding</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {filtered
                  .slice()
                  .sort((a, b) => {
                    if (a.status.toLowerCase() === "overdue" && b.status.toLowerCase() !== "overdue") return -1;
                    if (b.status.toLowerCase() === "overdue" && a.status.toLowerCase() !== "overdue") return 1;
                    return Number(b.amount_outstanding) - Number(a.amount_outstanding);
                  })
                  .map((inv) => (
                    <tr key={inv.id} className="clickable" onClick={() => setOpenInv(inv)}>
                      <td>
                        <b>{inv.invoice_number}</b>
                        {inv.lifecycle && <LifecycleProgress lc={inv.lifecycle} compact />}
                      </td>
                      <td>{inv.customer_name}</td>
                      <td className="muted">{inv.due_date ? fmtDate(inv.due_date) : "—"}</td>
                      <td>
                        <StatusPill status={inv.status} dueDate={inv.due_date} />
                      </td>
                      <td>
                        <ProcessStatusChip ps={inv.process_status} />
                      </td>
                      <td>
                        {inv.readiness_summary ? (
                          <ReadinessSummaryChip rs={inv.readiness_summary} />
                        ) : (
                          <span className="muted">—</span>
                        )}
                      </td>
                      <td className="num">
                        <span style={{ display: "inline-flex", gap: 8, alignItems: "center" }}>
                          {money(inv.amount_outstanding)}
                          {inv.process_status && (
                            <button
                              className="btn tiny ghost"
                              title="Open the evidence drawer for this invoice"
                              onClick={(e) => {
                                e.stopPropagation();
                                setEvidenceInv(inv);
                              }}
                            >
                              Evidence
                            </button>
                          )}
                        </span>
                      </td>
                      <td>
                        <button
                          className="btn tiny"
                          title="Open the full action panel for this invoice"
                          onClick={(e) => {
                            e.stopPropagation();
                            setPanelInv(inv);
                          }}
                        >
                          Action
                        </button>
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {openInv && <InvoiceDrawer inv={openInv} onClose={() => setOpenInv(null)} onEvidence={() => setEvidenceInv(openInv)} onPanel={() => setPanelInv(openInv)} onMarkPaid={() => { setPaying(openInv); setPayAmt(String(openInv.amount_outstanding)); setPayNote(""); setOpenInv(null); }} />}

      {evidenceInv && (
        <EvidenceDrawer
          invoice={evidenceInv}
          ps={evidenceInv.process_status}
          onClose={() => setEvidenceInv(null)}
        />
      )}

      {panelInv && (
        <InvoiceActionPanelModal
          invoiceId={panelInv.id}
          invoiceLabel={panelInv.invoice_number}
          onClose={() => setPanelInv(null)}
        />
      )}

      {paying && (
        <Modal title={`Record payment · ${paying.invoice_number}`} onClose={() => setPaying(null)}>
          <div className="muted" style={{ marginBottom: 10 }}>
            {paying.customer_name} · {money(paying.amount_outstanding)} outstanding. Recording a received payment
            updates your Money Recovered figure and the action queue.
          </div>
          <div className="field">
            <label htmlFor="pay-amt">Amount received</label>
            <input id="pay-amt" type="number" min="0" step="0.01" value={payAmt} onChange={(e) => setPayAmt(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="pay-note">Note (optional)</label>
            <input id="pay-note" value={payNote} onChange={(e) => setPayNote(e.target.value)} placeholder="e.g. wire received, check in mail" />
          </div>
          <div className="row-btns">
            <button className="btn b-pri" disabled={busy} onClick={confirmPaid}>
              {busy ? <Spinner /> : "Record payment"}
            </button>
            <button className="btn ghost" onClick={() => setPaying(null)}>
              Cancel
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}

function InvoiceDrawer({ inv, onClose, onMarkPaid, onEvidence, onPanel }: { inv: Invoice; onClose: () => void; onMarkPaid: () => void; onEvidence: () => void; onPanel: () => void }) {
  const lower = inv.status.toLowerCase();
  const open = lower !== "paid" && inv.amount_outstanding > 0;
  const ps = inv.process_status;
  const showEvidence = !!ps?.evidence_items?.length;
  const factOrder = ["created", "sent", "receipt", "po", "approval", "promise", "paid"];
  const factLabels: Record<string, string> = {
    created: "Created", sent: "Sent", receipt: "Receipt", po: "PO / reference",
    approval: "Approval", promise: "Promise", paid: "Paid",
  };
  let hint: string;
  if (lower === "paid") hint = "This invoice is fully settled. It no longer feeds the action queue or cash forecast.";
  else if (lower === "overdue") hint = "Past its due date. The AI treats this as at-risk cash and will prioritise it in the queue.";
  else if (!inv.due_date) hint = "No due date yet. Until one is set, the AI can't timebox this invoice in the forecast.";
  else {
    const diff = Math.ceil((new Date(inv.due_date).getTime() - Date.now()) / 86400000);
    hint =
      diff <= 7
        ? "Due within a week. Expect it in the 'due soon' window — follow-ups are likely to start soon."
        : "Due later. It sits in the forecast window but isn't chased yet.";
  }
  return (
    <div className="drawer-wrap">
      <div className="drawer-backdrop" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-label={inv.invoice_number}>
        <div className="drawer-head">
          <div>
            <div className="muted small">Invoice</div>
            <h3>{inv.invoice_number}</h3>
          </div>
          <button className="d-close" onClick={onClose} aria-label="close">
            <X size={18} />
          </button>
        </div>
        <div className="drawer-body">
          <div className="d-amount">
            <div className={`t-${lower === "paid" ? "green" : "amber"}`} style={{ fontSize: 26, fontWeight: 800 }}>
              {money(inv.amount_outstanding)}
            </div>
            <StatusPill status={inv.status} dueDate={inv.due_date} />
          </div>

          <div className="d-row">
            <span className="lab">Customer</span>
            <span className="val">{inv.customer_name}</span>
          </div>
          <div className="d-row">
            <span className="lab">Due date</span>
            <span className="val">{inv.due_date ? fmtDate(inv.due_date) : "not set"}</span>
          </div>
          <div className="d-row">
            <span className="lab">Outstanding</span>
            <span className="val num">{money(inv.amount_outstanding)}</span>
          </div>
          <div className="d-row">
            <span className="lab">Process status</span>
            <span className="val">
              <ProcessStatusChip ps={ps} />
            </span>
          </div>
          {inv.lifecycle && (
            <div className="d-row">
              <span className="lab">Lifecycle</span>
              <span className="val" style={{ display: "block" }}>
                <LifecycleProgress lc={inv.lifecycle} />
              </span>
            </div>
          )}
          {inv.readiness_summary && (
            <div className="d-row">
              <span className="lab">Send readiness</span>
              <span className="val">
                <ReadinessSummaryChip rs={inv.readiness_summary} />
              </span>
            </div>
          )}
          {ps?.evidence_status && (
            <div className="d-row">
              <span className="lab">Status is</span>
              <span className={`val ${ps.evidence_status === "UNKNOWN" ? "t-amber" : "t-green"}`}>
                {ps.evidence_status.toLowerCase()} — “{ps.evidence_status === "KNOWN" ? "a stored fact" : ps.evidence_status === "INFERRED" ? "derived from a stored fact" : "no evidence on file"}”
              </span>
            </div>
          )}

          {ps && (
            <div className="d-process">
              <div className="d-note" style={{ marginTop: 0 }}>
                <CalendarClock size={14} />
                <div>
                  <b>{ps.stage || ps.status_label}</b>
                  {ps.blocker && (
                    <p className="muted small" style={{ margin: "4px 0 0" }}>
                      Blocked on: {ps.blocker}
                    </p>
                  )}
                  {ps.facts && (
                    <ul className="pd-check" style={{ marginTop: 8 }}>
                      {factOrder.map((k) => {
                        const f = ps.facts?.[k];
                        if (!f) return null;
                        const st = f.state === "KNOWN" ? "ok" : f.state === "INFERRED" ? "inf" : "unknown";
                        return (
                          <li key={k} className={`pd-c-${st}`} title={f.note}>
                            <span className="pd-c-dot" />
                            {factLabels[k] || k}
                            <em>{f.state.toLowerCase()}</em>
                          </li>
                        );
                      })}
                    </ul>
                  )}
                </div>
              </div>
            </div>
          )}

          <div className="d-note">
            <CalendarClock size={14} />
            <div>
              <b>What the AI does with this</b>
              <p className="muted small" style={{ margin: "4px 0 0" }}>
                {hint}
              </p>
            </div>
          </div>
        </div>
        <div className="drawer-foot">
          {open && (
            <button className="btn b-pri" onClick={onMarkPaid}>
              Record payment
            </button>
          )}
          <button className="btn" onClick={onPanel}>
            Action panel
          </button>
          {showEvidence && (
            <button className="btn ghost" onClick={onEvidence}>
              Evidence
            </button>
          )}
          <button className="btn ghost" onClick={onClose}>
            Close
          </button>
        </div>
      </aside>
    </div>
  );
}