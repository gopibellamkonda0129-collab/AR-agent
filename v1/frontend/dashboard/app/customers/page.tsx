"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  fetchActionQueue,
  fetchCustomerDetail,
  fetchCustomers,
  fetchInvoiceActionPanel,
  fetchPayments,
  TYPE_LABEL,
  type ActionItem,
  type CustomerDetail,
  type Invoice,
  type InvoiceActionPanel,
  type Signal,
} from "../../lib/api";
import {
  BehaviorPanel,
  ChaseStrategyCard,
  CollectionsCard,
  CustomerProcessPanel,
  EvidenceDrawer,
  FollowUpComposer,
  Kpi,
  Modal,
  OwnerOverride,
  PageTitle,
  PriorityChip,
  PromiseBreakdownTable,
  Skeleton,
  Spinner,
  StuckPanel,
  WhyLateCard,
  fmtDate,
  initials,
  money,
  timeAgo,
  usePolling,
} from "../../lib/components";
import { BarChart, Mail, Sparkles } from "../../lib/icons";

export default function CustomersPage() {
  const customers = usePolling(fetchCustomers, 20000);
  const queue = usePolling(fetchActionQueue, 20000);
  const payments = usePolling(fetchPayments, 30000);
  const [openName, setOpenName] = useState<string | null>(null);
  const [detail, setDetail] = useState<CustomerDetail | null>(null);
  const [detailErr, setDetailErr] = useState("");
  const [loadingDetail, setLoadingDetail] = useState(false);
  const openedQRef = useRef(false);

  const paidThisMonth = useMemo(() => {
    const map: Record<string, number> = {};
    const now = new Date();
    for (const p of payments.data ?? []) {
      const d = new Date(p.paid_at);
      if (d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth()) {
        map[p.customer_name] = (map[p.customer_name] ?? 0) + p.amount;
      }
    }
    return map;
  }, [payments.data]);

  const actionFor = (name: string): ActionItem | undefined =>
    queue.data?.actions.find((a) => a.customer_name === name);

  const open = async (name: string) => {
    setOpenName(name);
    setDetail(null);
    setDetailErr("");
    setLoadingDetail(true);
    try {
      setDetail(await fetchCustomerDetail(name));
    } catch (e) {
      setDetailErr(String(e));
    } finally {
      setLoadingDetail(false);
    }
  };

  useEffect(() => {
    if (openedQRef.current) return;
    const q = new URLSearchParams(window.location.search).get("open");
    if (q) {
      openedQRef.current = true;
      open(q);
    }
  }, []);

  const total = customers.data?.reduce((s, c) => s + c.total_outstanding, 0) ?? null;
  const needing = customers.data?.filter((c) => c.open_signals > 0 || c.overdue_amount > 0).length ?? 0;

  return (
    <div className="page-body">
      <PageTitle title="Customers" sub="Every account with open money, signals, or promises." eyebrow="Ledger" />

      {customers.error && <div className="banner err">{customers.error}</div>}

      <section className="kpis">
        <Kpi label="Customers" value={String(customers.data?.length ?? 0)} sub="with ledgers in this workspace" />
        <Kpi label="Needs attention" value={String(needing)} sub="open signal or overdue balance" tone="info" />
        <Kpi label="Outstanding" value={money(total)} sub="sum of all open ledgers" tone="amber" />
        <Kpi label="Overdue promises" value={String((customers.data ?? []).reduce((s, c) => s + c.promises.filter((p) => p.status === "overdue").length, 0))} tone="red" sub="missed payment dates" />
      </section>

      {customers.loading && !customers.data ? (
        <div className="card">
          <div className="sk-list">
            <Skeleton lines={1} h={22} w="40%" br={8} />
            <Skeleton lines={5} h={46} br={10} />
          </div>
        </div>
      ) : customers.data && customers.data.length === 0 ? (
        <div className="card">
          <div className="empty-hint">
            <b>No customers yet.</b>
            <div className="muted">Import an invoice CSV/Excel in Invoices, or connect an inbox — customers get created from your data.</div>
          </div>
        </div>
      ) : (
        <div className="card">
          <div className="hd-inline">
            <div>
              <h2>All customers</h2>
              <div className="muted small">Click a row for the full account picture — timeline, signals, invoices and email.</div>
            </div>
            <span className="count">{customers.data?.length ?? 0}</span>
          </div>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Customer</th>
                  <th>Outstanding</th>
                  <th>Overdue</th>
                  <th>Signals</th>
                  <th>Promises</th>
                  <th>Priority</th>
                  <th>Next action</th>
                </tr>
              </thead>
              <tbody>
                {(customers.data ?? [])
                  .slice()
                  .sort((a, b) => b.total_outstanding - a.total_outstanding)
                  .map((c) => {
                    const a = actionFor(c.customer_name);
                    const attn = c.overdue_amount > 0 || c.open_signals > 0;
                    return (
                      <tr key={c.customer_name} onClick={() => open(c.customer_name)} className={`clickable${attn ? " row-attn" : ""}`}>
                        <td>
                          <div className="t-name">
                            <span className="avatar">{initials(c.customer_name)}</span>
                            <span>
                              <b>{c.customer_name}</b>
                              <em className="muted">{c.contact_email}</em>
                            </span>
                          </div>
                        </td>
                        <td className="num t-amber">{money(c.total_outstanding)}</td>
                        <td className={`num ${c.overdue_amount > 0 ? "t-red" : "muted"}`}>{money(c.overdue_amount)}</td>
                        <td className="num">
                          {c.open_signals > 0 ? <span className="badge b-type">{c.open_signals}</span> : <span className="muted">0</span>}
                        </td>
                        <td className="num">
                          {c.promises.length ? (
                            <span className={`badge ${c.promises.some((p) => p.status === "overdue") ? "b-state-overdue" : "b-state-upcoming"}`}>
                              {c.promises.length}
                            </span>
                          ) : (
                            <span className="muted">—</span>
                          )}
                        </td>
                        <td>{a ? <PriorityChip priority={a.priority} score={a.priority_score} /> : <span className="muted">—</span>}</td>
                        <td>
                          <span className={`muted small${a ? " t-strong" : ""}`}>{a ? a.action_label : "no action"}</span>
                        </td>
                      </tr>
                    );
                  })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {openName && (
        <Modal title={openName} onClose={() => setOpenName(null)} wide>
          {loadingDetail ? (
            <div className="sk-pad">
              <Spinner />
            </div>
          ) : detailErr ? (
            <div className="banner err">{detailErr}</div>
          ) : (
            detail && <CustomerDetailView detail={detail} paidThisMonth={paidThisMonth[detail.customer_name] ?? 0} onRefresh={() => open(openName)} />
          )}
        </Modal>
      )}
    </div>
  );
}

function PaymentReadinessCard({ detail }: { detail: CustomerDetail }) {
  const [panel, setPanel] = useState<InvoiceActionPanel | null>(null);
  const [err, setErr] = useState("");
  const open = detail.invoices.filter((i) => i.status.toLowerCase() !== "paid" && i.amount_outstanding > 0);
  const primary = open.length
    ? open.reduce((a, b) => (Number(b.amount_outstanding) > Number(a.amount_outstanding) ? b : a))
    : null;

  useEffect(() => {
    if (!primary) return;
    let live = true;
    setPanel(null);
    setErr("");
    fetchInvoiceActionPanel(primary.id)
      .then((p) => live && setPanel(p))
      .catch((e) => live && setErr(String(e)));
    return () => { live = false; };
  }, [primary?.id]);

  if (!primary) return null;
  const score = panel?.payment_readiness_score;

  return (
    <div className="panel intel-panel ci-panel">
      <div className="panel-head">
        <span className="fu-kicker" style={{ margin: 0 }}>
          <BarChart size={14} /> Payment readiness score
        </span>
        {score && (
          <span className={`pay-score pay-${score.tone}`}>
            <b>{score.score}</b>
            <span>{score.label}</span>
          </span>
        )}
      </div>
      {err ? (
        <div className="banner err">{err}</div>
      ) : !score ? (
        <div className="sk-pad"><Spinner /></div>
      ) : (
        <>
          <p className="muted small" style={{ margin: "6px 0 8px" }}>
            How ready this customer is to pay — based on {primary.invoice_number}, the largest open invoice on
            file. Every point is backed by evidence below.
          </p>
          <div className="sig-list">
            {score.signals.map((s) => (
              <div key={s.key} className="sig-row">
                <div className="sig-top">
                  <b>{s.label}</b>
                  <span className="muted small">{s.value}</span>
                  <span className="sig-w">{s.score}/{s.weight}</span>
                </div>
                <span className="sig-track">
                  <i
                    className={`sig-fill sig-${score.tone}`}
                    style={{ width: `${s.weight > 0 ? (s.score / s.weight) * 100 : 0}%` }}
                  />
                </span>
                <span className="muted small sig-reason">{s.reason}</span>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function CustomerDetailView({ detail, paidThisMonth, onRefresh }: { detail: CustomerDetail; paidThisMonth: number; onRefresh: () => void }) {
  const [compose, setCompose] = useState(false);
  const [evidenceInv, setEvidenceInv] = useState<{ invoice_number: string; customer_name?: string; process_status?: Invoice["process_status"] } | null>(null);
  const reco = detail.recommended_action;
  const asItem: ActionItem = {
    customer_name: detail.customer_name,
    customer_email: detail.contact_email,
    customer_first: detail.customer_name.split(" ")[0] || detail.customer_name,
    total_outstanding: detail.total_outstanding,
    overdue_amount: detail.overdue_amount,
    max_days_overdue: detail.max_days_overdue,
    due_this_week_amount: 0,
    invoice_count: detail.invoice_count,
    overdue_invoice_count: detail.invoices.filter((i) => i.status === "overdue").length,
    primary_invoice_number: detail.invoices[0]?.invoice_number || "",
    open_signal_count: detail.signals.filter((s) => !s.resolved).length,
    open_signal_types: detail.signals.filter((s) => !s.resolved).map((s) => s.signal_type),
    latest_signal: detail.signals.filter((s) => !s.resolved)[0]
      ? {
          signal_type: detail.signals.filter((s) => !s.resolved)[0].signal_type,
          summary: detail.signals.filter((s) => !s.resolved)[0].summary,
          created_at: detail.signals.filter((s) => !s.resolved)[0].created_at,
          priority: detail.signals.filter((s) => !s.resolved)[0].priority,
          resolved: false,
          source_email_body: "",
        }
      : null,
    last_response_days: null,
    promise: detail.promises[0]
      ? {
          promised_date: detail.promises[0].promised_date,
          promised_amount: detail.promises[0].promised_amount,
          status: detail.promises[0].status,
          days_late: detail.promises[0].days_late,
          related_invoice: "",
        }
      : null,
    action: reco.action,
    action_label: reco.action_label,
    reason: reco.reason,
    recommendation_confidence: reco.recommendation_confidence,
    suggested_follow_up_date: reco.suggested_follow_up_date,
    draft_type: reco.draft_type,
    priority: reco.priority,
    priority_score: reco.priority_score,
    priority_reasons: reco.priority_reasons,
    status: "active",
    snoozed_until: null,
    last_contacted_at: null,
    contact_note: "",
    ownership: detail.ownership as ActionItem["ownership"],
  };

  const openSignals = detail.signals.filter((s) => !s.resolved);
  const openPromises = detail.promises.filter((p) => p.status !== "overdue").length;
  const overduePromises = detail.promises.length - openPromises;

  return (
    <div className="cust-detail">
      <div className="cd-head">
        <div className="cd-id">
          <span className="avatar lg">{initials(detail.customer_name)}</span>
          <div>
            <div className="cd-name">{detail.customer_name}</div>
            <div className="muted small">{detail.contact_email}</div>
            {paidThisMonth > 0 && (
              <div className="paid-note">
                <span className="d-dot" /> paid {money(paidThisMonth)} this month
              </div>
            )}
          </div>
        </div>
        <div className="cd-actions">
          <PriorityChip priority={reco.priority} score={reco.priority_score} />
          <OwnerOverride item={asItem} onChanged={onRefresh} />
          {reco.action !== "no_action" && (
            <button className="btn b-pri small" onClick={() => setCompose(true)}>
              <Mail size={14} /> Review follow-up
            </button>
          )}
        </div>
      </div>

      <div className="cd-grid fin">
        <div className="cf">
          <b className="t-amber">{money(detail.total_outstanding)}</b>
          <span>Outstanding</span>
        </div>
        <div className="cf">
          <b className={detail.overdue_amount > 0 ? "t-red" : "muted"}>{money(detail.overdue_amount)}</b>
          <span>Overdue</span>
        </div>
        <div className="cf">
          <b>{detail.invoice_count}</b>
          <span>Invoices</span>
        </div>
        <div className="cf">
          <b>{openPromises}</b>
          <span>Open promises{overduePromises > 0 ? ` · ${overduePromises} missed` : ""}</span>
        </div>
      </div>

      <div className="ai-reco">
        <Sparkles size={15} />
        <div>
          <b>AI recommends …</b>
          <div className="muted small">
            {reco.action_label}
            {reco.suggested_follow_up_date ? ` — suggested by ${fmtDate(reco.suggested_follow_up_date)}.` : "."} {reco.reason}
          </div>
        </div>
      </div>

      <div className="intel-row">
        <CollectionsCard c={detail.collections} readiness={detail.readiness} pre_due={detail.pre_due} />
        <div style={{ display: "flex", flexDirection: "column", gap: 10, minWidth: 0 }}>
          <BehaviorPanel behavior={detail.behavior} />
          <PromiseBreakdownTable rows={detail.behavior?.promise_breakdown} />
        </div>
      </div>

      <PaymentReadinessCard detail={detail} />

      <div className="intel-row">
        <StuckPanel stuck={detail.ar_process?.current} />
        <CustomerProcessPanel ar={detail.ar_process} />
      </div>

      {(detail.ar_process?.current?.current_stage || "").length > 0 && (
        <div className="proc-banner">
          <span className="chip chip-violet">{detail.ar_process.current.current_stage}</span>
          {detail.ar_process.current.blocker && (
            <span className="chip chip-amber">{detail.ar_process.current.blocker}</span>
          )}
          <span className="muted small">
            {detail.ar_process.current.where}
            {detail.ar_process.current.next_action ? ` — next: ${detail.ar_process.current.next_action}` : ""}
          </span>
        </div>
      )}

      <div className="intel-row">
        <WhyLateCard w={detail.why_late} />
        <ChaseStrategyCard s={detail.strategy} />
      </div>

      <div className="cd-grid">
        <section className="cd-sec">
          <h4>What changed · timeline</h4>
          {detail.timeline.length === 0 && <div className="muted small">No activity indexed yet.</div>}
          <div className="timeline">
            {detail.timeline.map((t, i) => (
              <div key={i} className="tl">
                <span className="tl-dot" data-k={t.kind} />
                <div>
                  <div className="tl-title">{t.title}</div>
                  <div className="tl-date muted small">{t.date}</div>
                  {t.detail && <div className="tl-detail muted">{t.detail}</div>}
                  {t.topics && t.topics.length > 0 && (
                    <div className="tl-topics">
                      {t.topics.map((topic, j) => (
                        <span key={j} className="chip chip-violet mini">{topic}</span>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </section>

        <section className="cd-sec">
          <h4>What&apos;s happening</h4>
          <div className="muted small" style={{ marginBottom: 8 }}>
            {openSignals.length === 0
              ? "No open signals. Cash may still be at risk from overdue invoices."
              : `${openSignals.length} open signal${openSignals.length === 1 ? "" : "s"}:`}
          </div>
          {openSignals.map((s: Signal) => (
            <div key={s.id} className="signal">
              <div className="head">
                <span className="badge b-type">{TYPE_LABEL[s.signal_type] || s.signal_type}</span>
                <span className={`badge b-pri-${s.priority}`}>{s.priority}</span>
                <span className="muted small">{timeAgo(s.created_at)}</span>
              </div>
              <div className="summary">{s.summary}</div>
              {s.related_invoice && <div className="muted small">related invoice: {s.related_invoice}</div>}
            </div>
          ))}
        </section>

        <section className="cd-sec">
          <h4>Invoices</h4>
          {detail.invoices.length === 0 && <div className="muted small">No invoices on file.</div>}
          <div className="inv-list">
            {detail.invoices.map((inv) => (
              <div key={inv.id} className="inv-row">
                <span>
                  <b>{inv.invoice_number}</b>
                  <span className="muted small">{inv.due_date ? `due ${fmtDate(inv.due_date)}` : "no due date"}</span>
                </span>
                <span>
                  <span className={`inv-st st-${inv.status}`}>{inv.status}</span>
                  {inv.process_status && (
                    <button
                      className="btn tiny ghost"
                      title="Open evidence for this invoice"
                      onClick={() =>
                        setEvidenceInv({
                          invoice_number: inv.invoice_number,
                          customer_name: detail.customer_name,
                          process_status: inv.process_status,
                        })
                      }
                    >
                      Evidence
                    </button>
                  )}
                  <span className={`num ${inv.status === "overdue" ? "t-red" : "muted"}`}>{money(inv.amount_outstanding)}</span>
                </span>
              </div>
            ))}
          </div>
        </section>

        <section className="cd-sec">
          <h4>Emails</h4>
          {detail.emails.length === 0 && <div className="muted small">No customer email indexed yet.</div>}
          {detail.emails.map((e) => (
            <div key={e.id} className="inv-row">
              <span className="e-subj">{e.subject}</span>
              <span className="muted small">{timeAgo(e.received_at)}</span>
            </div>
          ))}
        </section>
      </div>

      {compose && <FollowUpComposer item={asItem} onClose={() => setCompose(false)} />}

      {evidenceInv && (
        <EvidenceDrawer
          invoice={evidenceInv}
          ps={evidenceInv.process_status}
          onClose={() => setEvidenceInv(null)}
        />
      )}
    </div>
  );
}