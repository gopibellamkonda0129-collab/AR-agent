"use client";

import { useMemo } from "react";
import { fetchArProcess, fetchInvoices, fetchPayments, fetchWeeklyReport } from "../../lib/api";
import { AgingBars } from "../../lib/charts";
import { ArProcessCard, Kpi, PageTitle, PriorityChip, Spinner, money, num, usePolling } from "../../lib/components";
import { Sparkles } from "../../lib/icons";

const agingBuckets = (invoices: { status: string; amount_outstanding: number; due_date: string | null }[]) => {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const mk = (label: string, tone: string) => ({ label, amount: 0, tone });
  const buckets = [
    mk("Current", "linear-gradient(90deg,#4cbf9a,#3aa982)"),
    mk("1–30 days", "linear-gradient(90deg,#7c8cff,#5a68c9)"),
    mk("31–60 days", "linear-gradient(90deg,#d8a04a,#b98532)"),
    mk("61–90 days", "linear-gradient(90deg,#e76978,#c65360)"),
    mk("90+ days", "linear-gradient(90deg,#e76978,#b24a58)"),
  ];
  for (const inv of invoices) {
    if ((inv.status || "").toLowerCase() === "paid" || !inv.amount_outstanding) continue;
    if (!inv.due_date) {
      buckets[0].amount += inv.amount_outstanding;
      continue;
    }
    const due = new Date(inv.due_date + "T00:00:00");
    const days = Math.max(0, Math.floor((today.getTime() - due.getTime()) / 86400000));
    const idx = days === 0 ? 0 : days <= 30 ? 1 : days <= 60 ? 2 : days <= 90 ? 3 : 4;
    buckets[idx].amount += inv.amount_outstanding;
  }
  return buckets;
};

export default function ReportsPage() {
  const r = usePolling(fetchWeeklyReport, 120000);
  const invoices = usePolling(fetchInvoices, 60000);
  const payments = usePolling(fetchPayments, 60000);
  const ar = usePolling(fetchArProcess, 180000);

  const aging = useMemo(() => agingBuckets(invoices.data?.invoices ?? []), [invoices.data]);
  const pastDue = aging.slice(1).reduce((s, b) => s + b.amount, 0);

  const collectedThisMonth = useMemo(() => {
    const now = new Date();
    return (payments.data ?? []).reduce((s, p) => {
      const d = new Date(p.paid_at);
      return d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth() ? s + p.amount : s;
    }, 0);
  }, [payments.data]);

  return (
    <div className="page-body">
      <PageTitle title="Weekly receivables brief" sub="One page: cash that flowed in, promises broken, disputes open, and who to chase next week." eyebrow="Understand" />

      {r.loading && !r.data ? (
        <div className="full-center">
          <Spinner />
          <span className="muted">Folding this week&apos;s numbers…</span>
        </div>
      ) : r.error ? (
        <div className="banner err">{r.error}</div>
      ) : r.data ? (
        <>
          <div className="muted small" style={{ margin: "-6px 0 14px" }}>
            Generated {r.data.generated_at} · covering {r.data.week.start} → {r.data.week.end}
            {r.data.cash_collected.note && <> · {r.data.cash_collected.note}</>}
          </div>

          <section className="kpis">
            <Kpi label="Cash collected" value={money(r.data.cash_collected.amount)} tone="green" sub={`${r.data.cash_collected.count} payment(s) recorded`} />
            <Kpi label="Newly overdue" value={money(r.data.new_overdue_invoices.amount)} tone="amber" sub={`${r.data.new_overdue_invoices.count} invoice(s) went overdue`} />
            <Kpi label="Promises missed" value={String(r.data.missed_payment_promises.count)} tone="red" sub={money(r.data.missed_payment_promises.amount)} />
            <Kpi label="Open disputes" value={String(r.data.open_disputes.count)} tone="violet" sub={money(r.data.open_disputes.amount)} />
          </section>

          <section className="kpis">
            <Kpi label="Expected incoming" value={money(r.data.expected_incoming_payments)} sub="promised next 30 days" tone="green" />
            <Kpi label="Escalation needed" value={String((r.data.customers_requiring_escalation || []).length)} tone="red" sub="no response, past due, past promises" />
            <Kpi label="Collected this month" value={money(collectedThisMonth)} tone="green" sub="from the payments you logged" />
            <Kpi label="Past-due exposure" value={money(pastDue)} tone="amber" sub="all buckets beyond current" />
          </section>

          <div className="grid-main">
            <div className="card">
              <div className="hd-inline">
                <h2>
                  AR aging
                  <span className="count">by due date</span>
                </h2>
              </div>
              <AgingBars buckets={aging} />
              <div className="muted small" style={{ marginTop: 10 }}>
                Open balances bucketed by how overdue they are. The older the bucket, the harder it is to collect — chase or escalate accordingly.
              </div>
            </div>

            <div className="card">
              <div className="ai-reco" style={{ marginBottom: 14 }}>
                <Sparkles size={15} />
                <div>
                  <b>Executive read</b>
                  <div className="muted small" style={{ marginTop: 4, lineHeight: 1.55 }}>
                    {r.data.cash_collected.count > 0
                      ? `${r.data.cash_collected.count} payment${r.data.cash_collected.count === 1 ? "" : "s"} this window worth ${money(r.data.cash_collected.amount)}. `
                      : "No payments recorded this window yet. "}
                    {r.data.missed_payment_promises.count > 0
                      ? `${r.data.missed_payment_promises.count} promise${r.data.missed_payment_promises.count === 1 ? "" : "s"} broken worth ${money(r.data.missed_payment_promises.amount)}. `
                      : "No broken promises this window. "}
                    {r.data.open_disputes.count > 0
                      ? `${r.data.open_disputes.count} dispute${r.data.open_disputes.count === 1 ? "" : "s"} open worth ${money(r.data.open_disputes.amount)}.`
                      : "No open disputes."}
                  </div>
                </div>
              </div>

              <h2>Newly overdue this week</h2>
              {r.data.new_overdue_invoices.customers.length === 0 ? (
                <div className="empty-hint">
                  <b>None. Nice.</b>
                  <div className="muted">No invoices crossed their due date without payment this week.</div>
                </div>
              ) : (
                <div className="pills">{r.data.new_overdue_invoices.customers.map((c) => <span key={c} className="chip">{c}</span>)}</div>
              )}
            </div>
          </div>

          <div className="card">
            <h2>Priority for next week</h2>
            {r.data.recommended_priorities_next_week.length === 0 ? (
              <div className="empty-hint">
                <b>The queue is clear.</b>
                <div className="muted">Nothing scheduled — enjoy the quiet week.</div>
              </div>
            ) : (
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Customer</th>
                      <th>Outstanding</th>
                      <th>Recommended action</th>
                      <th>Priority</th>
                    </tr>
                  </thead>
                  <tbody>
                    {r.data.recommended_priorities_next_week.map((p) => (
                      <tr key={p.customer_name}>
                        <td>
                          <b>{p.customer_name}</b>
                        </td>
                        <td className="num">{money(p.amount)}</td>
                        <td className="muted small">{p.action}</td>
                        <td>
                          <PriorityChip priority={p.priority} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {r.data.largest_overdue_accounts.length > 0 && (
            <div className="card">
              <h2>Largest overdue accounts</h2>
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Customer</th>
                      <th className="num">Overdue</th>
                      <th className="num">Days</th>
                      <th>Priority</th>
                    </tr>
                  </thead>
                  <tbody>
                    {r.data.largest_overdue_accounts.map((a) => (
                      <tr key={a.customer_name}>
                        <td>
                          <b>{a.customer_name}</b>
                        </td>
                        <td className="num t-red">{money(a.overdue_amount)}</td>
                        <td className="num">{num(a.days_overdue)}</td>
                        <td>
                          <PriorityChip priority={a.priority} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          <div className="sec-block">
            <div className="hd-inline">
              <h2>
                The AR process — observed vs recommended
                <span className="count">documented from your workspace</span>
              </h2>
              <div className="muted small">
                Which steps in getting from “invoice created” to “cash on the bank” have evidence behind them, and which are still unknown.
              </div>
            </div>
            {ar.loading && !ar.data ? (
              <div className="full-center" style={{ minHeight: 120 }}>
                <Spinner />
              </div>
            ) : ar.error ? (
              <div className="banner err">{ar.error}</div>
            ) : (
              <ArProcessCard doc={ar.data ?? undefined} />
            )}
          </div>
        </>
      ) : (
        <div className="empty-hint">No report yet.</div>
      )}
    </div>
  );
}