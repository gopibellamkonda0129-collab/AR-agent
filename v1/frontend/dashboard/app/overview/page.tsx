"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  fetchActionQueue,
  fetchForecast,
  fetchInvoices,
  fetchMoneyRecovered,
  fetchPayments,
  fetchWeeklyReport,
  markContacted,
  reactivateCustomer,
  TYPE_LABEL,
  type ActionItem,
  type Invoice,
} from "../../lib/api";
import {
  ActionItemView,
  AnimatedNumber,
  EmptyState,
  FilterChips,
  FollowUpComposer,
  Modal,
  PageTitle,
  SnoozeModal,
  money,
  usePolling,
} from "../../lib/components";
import { AreaChart, RingGauge, TrendChart } from "../../lib/charts";
import { ArrowUpRight, Eye, Quote, Sparkles, X } from "../../lib/icons";

function dayStart(d: Date) {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate());
}

function parseDueDate(s: string | null): Date | null {
  if (!s) return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s);
  if (!m) return null;
  return new Date(+m[1], +m[2] - 1, +m[3]);
}

function buildTrend(
  invs: Invoice[],
  pays: { paid_at: string; amount: number }[],
  days: number
): { out: number[]; od: number[]; col: number[]; labels: string[] } {
  const today = dayStart(new Date());
  const idx = (i: number) => {
    const d = new Date(today);
    d.setDate(d.getDate() - i);
    return d;
  };
  const ts = (d: Date) => d.getTime();

  const out: number[] = new Array(days).fill(0);
  const od: number[] = new Array(days).fill(0);
  const col: number[] = new Array(days).fill(0);

  const unpaid = invs.filter((i) => i.status.toLowerCase() !== "paid");
  const outstandingNow = unpaid.reduce((s, i) => s + i.amount_outstanding, 0);

  const pay = pays
    .map((p) => ({ t: ts(dayStart(new Date(p.paid_at))), amt: p.amount }))
    .filter((p) => p.t >= ts(idx(days - 1)) && p.t <= ts(idx(0)));

  for (let i = 0; i < days; i++) {
    const t = ts(idx(i));
    let after = 0;
    for (const p of pay) if (p.t > t) after += p.amt;
    out[i] = outstandingNow + after;
  }

  const due = unpaid
    .filter((i) => i.due_date)
    .map((i) => ({ due: ts(parseDueDate(i.due_date)!), amt: i.amount_outstanding }));
  for (let i = 0; i < days; i++) {
    const t = ts(idx(i));
    let s = 0;
    for (const d of due) if (d.due <= t) s += d.amt;
    od[i] = s;
  }

  let run = 0;
  for (let i = days - 1; i >= 0; i--) {
    const t = ts(idx(i));
    for (const p of pay) if (p.t === t) run += p.amt;
    col[i] = run;
  }

  const labels = new Array(days).fill(0).map((_, i) =>
    idx(i).toLocaleDateString("en-US", { month: "short", day: "numeric" })
  );
  return { out, od, col, labels };
}

const riskBands = [
  { key: "critical", label: "Critical", min: 60, rc: "var(--red)" },
  { key: "high", label: "High", min: 31, rc: "var(--amber)" },
  { key: "moderate", label: "Moderate", min: 1, rc: "var(--blue)" },
] as const;

export default function OverviewPage() {
  const queue = usePolling(fetchActionQueue, 20000);
  const forecast = usePolling(fetchForecast, 60000);
  const brief = usePolling(fetchWeeklyReport, 120000);
  const recovered = usePolling(fetchMoneyRecovered, 60000);
  const invoices = usePolling(fetchInvoices, 60000);
  const payments = usePolling(fetchPayments, 60000);

  const [reviewing, setReviewing] = useState<ActionItem | null>(null);
  const [snoozing, setSnoozing] = useState<ActionItem | null>(null);
  const [filter, setFilter] = useState("all");
  const [contactNote, setContactNote] = useState<ActionItem | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [dismissedBrief, setDismissedBrief] = useState(false);
  const dismiss = () => setDismissedBrief(true);
  const [onboarded, setOnboarded] = useState(false);
  const [selected, setSelected] = useState<ActionItem | null>(null);
  const [range, setRange] = useState<7 | 30 | 90 | 180>(30);

  useEffect(() => {
    try {
      setOnboarded(localStorage.getItem("ar.onboarded") === "1");
    } catch {
      setOnboarded(true);
    }
  }, []);

  const finishOnboarding = () => {
    try {
      localStorage.setItem("ar.onboarded", "1");
    } catch {}
    setOnboarded(true);
  };

  const k = queue.data?.kpis;

  const totalNext30 = useMemo(() => {
    const f = forecast.data;
    if (!f) return null;
    const keys = ["expected_today", "expected_this_week", "expected_next_30_days"];
    return f.buckets.reduce((s, b) => s + (keys.includes(b.key) ? b.amount : 0), 0);
  }, [forecast.data]);

  /* actions */
  const actions = queue.data?.actions ?? [];

  const selectedItem = useMemo(
    () =>
      selected
        ? (actions.find((a) => a.customer_name === selected.customer_name) ?? selected)
        : null,
    [selected, actions]
  );

  const counts = useMemo(() => {
    const c: Record<string, number> = { all: actions.length };
    actions.forEach((a) => {
      c[a.priority] = (c[a.priority] ?? 0) + 1;
    });
    actions.forEach((a) => {
      (a.open_signal_types ?? []).forEach((t) => {
        c[t] = (c[t] ?? 0) + 1;
      });
      if (!a.latest_signal) c.noresponse = (c.noresponse ?? 0) + 1;
    });
    return c;
  }, [actions]);

  const filtered = useMemo(() => {
    if (filter === "all") return actions;
    if (filter === "critical" || filter === "high" || filter === "medium" || filter === "low") {
      return actions.filter((a) => a.priority === filter);
    }
    if (filter === "noresponse") return actions.filter((a) => !a.latest_signal);
    return actions.filter((a) => (a.open_signal_types ?? []).includes(filter));
  }, [actions, filter]);

  const chips = [
    { key: "all", label: "All", count: counts.all, active: filter === "all", onClick: () => setFilter("all") },
    { key: "critical", label: "Critical", count: counts.critical ?? 0, active: filter === "critical", onClick: () => setFilter("critical"), tone: "var(--red)" },
    { key: "high", label: "High", count: counts.high ?? 0, active: filter === "high", onClick: () => setFilter("high"), tone: "var(--amber)" },
    { key: "payment_promise", label: "Payment Promise", count: counts.payment_promise ?? 0, active: filter === "payment_promise", onClick: () => setFilter("payment_promise"), tone: "var(--violet)" },
    { key: "dispute", label: "Dispute", count: counts.dispute ?? 0, active: filter === "dispute", onClick: () => setFilter("dispute"), tone: "var(--purple)" },
    { key: "missing_invoice", label: "Missing Invoice", count: counts.missing_invoice ?? 0, active: filter === "missing_invoice", onClick: () => setFilter("missing_invoice"), tone: "var(--info)" },
    { key: "noresponse", label: "No Response", count: counts.noresponse ?? 0, active: filter === "noresponse", onClick: () => setFilter("noresponse"), tone: "var(--faint)" },
    { key: "documentation_request", label: "Docs Requested", count: counts.documentation_request ?? 0, active: filter === "documentation_request", onClick: () => setFilter("documentation_request"), tone: "var(--muted)" },
  ];

  /* AI insight text — built only from real queue numbers */
  const topType = useMemo(() => {
    const m = new Map<string, number>();
    actions.forEach((a) => {
      (a.open_signal_types ?? []).forEach((t) => m.set(t, (m.get(t) ?? 0) + 1));
    });
    if (actions.some((a) => !a.latest_signal)) m.set("noresponse", (m.get("noresponse") ?? 0) + 1);
    let best = "noresponse";
    let bestN = 0;
    m.forEach((n, t) => {
      if (n > bestN) {
        bestN = n;
        best = t;
      }
    });
    return bestN === 0 ? null : best;
  }, [actions]);

  const trend = useMemo(() => {
    if (!invoices.data) return null;
    return buildTrend(invoices.data.invoices, payments.data ?? [], range);
  }, [invoices.data, payments.data, range]);

  const insight = (() => {
    if (!k) return null;
    const hp = k.high_priority_customers;
    const op = k.overdue_promises;
    const head = `${actions.length} account${actions.length === 1 ? "" : "s"} need${actions.length === 1 ? "s" : ""} a follow-up today`;
    const mid =
      hp > 0 ? `${hp} of them critical or high priority.` : "No critical or high-priority accounts right now.";
    const tail =
      op > 0
        ? `${op} payment promise${op === 1 ? "" : "s"} already missed — chase before you draft anything else.`
        : topType
          ? `Most common trigger: ${topType === "noresponse" ? "no response from the customer" : TYPE_LABEL[topType] || topType}.`
          : "Every payment promise is on track.";
    return { head, mid, tail };
  })();

  const confirmContacted = async (item: ActionItem) => {
    setBusy(true);
    setMsg("");
    try {
      await markContacted(item.customer_name, note || "Marked contacted — follow-up sent.");
      queue.reload();
      setContactNote(null);
      setNote("");
    } catch (e) {
      setMsg(String(e));
    } finally {
      setBusy(false);
    }
  };

  const react = async (item: ActionItem) => {
    try {
      await reactivateCustomer(item.customer_name);
      queue.reload();
    } catch (e) {
      setMsg(String(e));
    }
  };

  if (queue.loading && !queue.data) {
    return (
      <div className="page-body">
        <div className="skel-main fade-up" aria-label="Loading your workspace">
          <div className="skel skel-hero" />
          <div className="skel-track">
            <div className="skel" />
            <div className="skel" />
            <div className="skel" />
          </div>
          <div className="skel skel-list" />
        </div>
      </div>
    );
  }

  if (queue.error && !queue.data) {
    return (
      <div className="page-body">
        <PageTitle title="Who should I chase today?" />
        <div className="banner err">
          {queue.error}
          <span className="muted">
            {" "}
            Is the backend running? Start it with <code>python app.py</code> in <code>v1/backend</code>.
          </span>
        </div>
      </div>
    );
  }

  const overduePct = k?.total_outstanding ? Math.round((k.overdue / k.total_outstanding) * 100) : 0;
  const cashPct = k?.total_outstanding ? Math.round((k.cash_at_risk / k.total_outstanding) * 100) : 0;
  const briefPriorities = (brief.data?.recommended_priorities_next_week ?? []).slice(0, 3);

  const riskSegs = (() => {
    const list = invoices.data?.invoices ?? [];
    const sums: Record<string, number> = { critical: 0, high: 0, moderate: 0 };
    const now = dayStart(new Date()).getTime();
    list.forEach((i) => {
      if (i.status.toLowerCase() === "paid") return;
      const due = parseDueDate(i.due_date);
      if (!due) return;
      const daysLate = Math.floor((now - due.getTime()) / 86400000);
      if (daysLate <= 0) return;
      const band = riskBands.find((b) => daysLate >= b.min);
      if (band) sums[band.key] += i.amount_outstanding;
    });
    const total = sums.critical + sums.high + sums.moderate;
    if (!total) return [];
    return riskBands
      .map((b) => ({ label: b.label, amt: sums[b.key], rc: b.rc }))
      .filter((r) => r.amt > 0)
      .map((r) => ({ ...r, pct: Math.round((r.amt / total) * 100) }));
  })();

  return (
    <div className="page-body">
      <PageTitle
        eyebrow="AI Receivables Assistant"
        title="Who should I chase today?"
        sub="The assistant reads your invoice ledger and customer email, then surfaces who needs a follow-up, why, and what to say — for your approval."
      />

      {!onboarded && (
        <div className="onboard card fade-up">
          <div className="onboard-title">
            <Sparkles size={16} /> Get your workspace up and running
          </div>
          <div className="steps">
            <div className="step">
              <span className="num">1</span>
              <div>
                <b>Upload invoices</b>
                <p>Bring your real ledger in from a CSV on the Invoices page. This is the ground truth for everything the assistant tells you.</p>
              </div>
            </div>
            <div className="step">
              <span className="num">2</span>
              <div>
                <b>Connect your mailbox</b>
                <p>Authorize the inbox your customers write to. The assistant reads it for promises, disputes, and red flags.</p>
              </div>
            </div>
            <div className="step">
              <span className="num">3</span>
              <div>
                <b>Analyze &amp; approve</b>
                <p>Watch the queue fill with who to chase, why, and a ready draft. Review, edit, and approve — nothing sends itself.</p>
              </div>
            </div>
          </div>
          <div className="onboard-cta">
            <span className="muted small">
              The accounts below are labeled sample data so you can see the assistant working immediately.
            </span>
            <button className="btn ghost small" onClick={finishOnboarding}>
              Got it — show me my workspace
            </button>
          </div>
        </div>
      )}

      {recovered.data && (
        <div className="money-strip fade-up">
          <span className="ms-label">Money recovered</span>
          <span className="ms-value">
            <AnimatedNumber value={recovered.data.this_month || recovered.data.total} format={(n) => money(n)} />
          </span>
          {recovered.data.this_month > 0 && (
            <span className="ms-note">
              this month · {money(recovered.data.last_month)} last month
            </span>
          )}
          <span className="ms-hint" title="Money recovered = recorded payments made against your invoices. Only ever reflects the payments you log — never invented.">
            <Eye size={13} style={{ verticalAlign: -2 }} /> what&apos;s tracked?
          </span>
        </div>
      )}

      {/* hero — one dominant financial overview */}
      <section className="hero-card">
        <div className="hero-top">
          <div className="hero-primary">
            <div className="hero-kicker">
              <span className="ring-mini" /> Total outstanding
            </div>
            <div className="hero-fig">
              <AnimatedNumber value={k?.total_outstanding ?? 0} format={(n) => money(n)} duration={1000} />
            </div>
            <div className="hero-row">
              {k && queue.data && (
                <span className="badge b-promise">{queue.data.actions.length} in queue</span>
              )}
              {k && <span className="badge b-risk">{cashPct}% of AR at risk</span>}
              <span className="muted small">
                cash at risk {money(k?.cash_at_risk)}
                {k && (k.amount_x_days_total ?? 0) > 0 && <> · {money(k.amount_x_days_total)} amount×days</>}
              </span>
            </div>
          </div>

          <div className="hero-risk">
            <div className="hero-risk-head">
              <span className="hero-risk-label">Cash at risk</span>
              <span className="hero-risk-pct">{overduePct}% of outstanding</span>
            </div>
            <div className="hero-risk-body">
              <RingGauge
                value={k?.overdue ?? 0}
                max={k?.total_outstanding ?? 1}
                size={96}
                stroke={9}
                tone="var(--red)"
                center={<b>{overduePct}%</b>}
              />
              <div>
                <div className="hero-risk-num">
                  <AnimatedNumber value={k?.cash_at_risk ?? 0} format={(n) => money(n)} duration={800} />
                </div>
                <div className="muted small" style={{ marginTop: 2 }}>
                  outstanding or overdue, signal-backed
                </div>
              </div>
            </div>
            <div className="risk-seg">
              {riskSegs.length > 0 ? (
                riskSegs.map((r) => (
                  <div key={r.label} className="risk-row">
                    <span style={{ display: "inline-flex", alignItems: "center", gap: 7, fontWeight: 650, color: "var(--muted)" }}>
                      <span className="rc" style={{ ["--rc" as string]: r.rc }} /> {r.label}
                    </span>
                    <div className="risk-track">
                      <div className="risk-fill" style={{ ["--rc" as string]: r.rc, width: `${r.pct}%` }} />
                    </div>
                    <div style={{ textAlign: "right" }}>
                      <b>{money(r.amt)}</b>
                      <span className="muted small" style={{ display: "block" }}>{r.pct}%</span>
                    </div>
                  </div>
                ))
              ) : (
                <span className="muted small">No invoices yet — import a ledger to see risk build-up.</span>
              )}
              <span className="muted small" style={{ marginTop: 2 }}>
                split by days overdue: critical ≥ 60 · high 31–59 · moderate 1–30
              </span>
            </div>
          </div>
        </div>

        <div className="hero-secondary">
          <div className="hs-item hs-amber">
            <span className="hs-dot" />
            <div>
              <span>Overdue</span>
              <b>
                <AnimatedNumber value={k?.overdue ?? 0} format={(n) => money(n)} duration={800} />
              </b>
            </div>
            <span className="hs-sub">{k?.overdue_promises ?? 0} promises late</span>
            <span className="hs-spark">
              <AreaChart points={trend ? trend.od.slice(-7) : []} height={30} tone="var(--amber)" showDots={false} />
            </span>
          </div>
          <div className="hs-item hs-green">
            <span className="hs-dot" />
            <div>
              <span>Expected 30 days</span>
              <b>
                <AnimatedNumber value={totalNext30 ?? 0} format={(n) => money(n)} duration={900} />
              </b>
            </div>
            <span className="hs-sub">cumulative promises</span>
            <span className="hs-spark">
              <AreaChart points={trend ? trend.col.slice(-7) : []} height={30} tone="var(--green)" showDots={false} />
            </span>
          </div>
          <div className="hs-item hs-blue">
            <span className="hs-dot" />
            <div>
              <span>Due this week</span>
              <b>
                <AnimatedNumber value={k?.due_this_week ?? 0} format={(n) => money(n)} duration={800} />
              </b>
            </div>
            <span className="hs-sub">follow-up window</span>
            <span className="hs-spark">
              <AreaChart points={trend ? trend.out.slice(-7) : []} height={30} tone="var(--blue)" showDots={false} />
            </span>
          </div>
        </div>

        <div className="hero-chart">
          <div className="hc-head">
            <b className="hc-title">Receivables trend</b>
            <div className="hc-legend">
              <span className="legend-item">
                <span className="sw" style={{ ["--lc" as string]: "var(--blue)" }} /> Outstanding
              </span>
              <span className="legend-item">
                <span className="sw" style={{ ["--lc" as string]: "var(--red)" }} /> Overdue
              </span>
              <span className="legend-item">
                <span className="sw" style={{ ["--lc" as string]: "var(--green)" }} /> Collected
              </span>
            </div>
            <div className="hc-range">
              {([7, 30, 90, 180] as const).map((d) => (
                <button key={d} className={range === d ? "active" : ""} onClick={() => setRange(d)}>
                  {d === 180 ? "6M" : `${d}D`}
                </button>
              ))}
            </div>
          </div>
          {trend ? (
            <TrendChart labels={trend.labels} outstanding={trend.out} overdue={trend.od} collected={trend.col} />
          ) : (
            <div className="empty-hint">
              <b>No trend yet.</b>
              <div className="muted">Import invoices and record payments to see your receivables trend build up.</div>
            </div>
          )}
          <div className="hc-note">
            Outstanding = open balances · Overdue = unpaid past due date · Collected = recorded payments. Point at the
            chart for details.
          </div>
        </div>
      </section>

      {k && (
        <div className="flow-card fade-up">
          <div className="flow-kicker">Money movement</div>
          <div className="flow">
            <div className="flow-node fn-blue">
              <span className="fn-lab">Outstanding</span>
              <b>{money(k.total_outstanding)}</b>
            </div>
            <span className="flow-arrow">&#8594;</span>
            <div className="flow-node fn-violet">
              <span className="fn-lab">Expected 30 days</span>
              <b>{money(totalNext30 ?? 0)}</b>
            </div>
            <span className="flow-arrow">&#8594;</span>
            <div className="flow-node fn-green">
              <span className="fn-lab">Collected</span>
              <b>{money(recovered.data?.total ?? 0)}</b>
            </div>
            <span className="flow-arrow">&#8594;</span>
            <div className="flow-node fn-emerald">
              <span className="fn-lab">Recovered this month</span>
              <b>{money(recovered.data?.this_month ?? 0)}</b>
            </div>
          </div>
        </div>
      )}

      {queue.error && <div className="banner err">{queue.error}</div>}
      {msg && <div className={`banner ${msg.includes(":") ? "err" : ""}`}>{msg}</div>}

      <section className="grid-main today">
        <div className="stack" style={{ display: "grid", gap: 16 }}>
          {insight && (
            <div className="ai-panel fade-up">
              <div className="ai-kicker">
                <Sparkles size={15} /> Today&apos;s AI brief
              </div>
              {actions.length > 0 && (
                <div className="ai-stat">
                  <span>
                    <b>{actions.length}</b> accounts need attention
                  </span>
                  {k && (
                    <span>
                      <b>{money(k.cash_at_risk)}</b> cash at risk
                    </span>
                  )}
                  {k && k.overdue_promises > 0 && (
                    <span>
                      <b>{k.overdue_promises}</b> promise{k.overdue_promises === 1 ? "" : "s"} missed
                    </span>
                  )}
                </div>
              )}
              <div className="ai-summary">
                {insight.head}. <b>{insight.mid}</b> {insight.tail}
              </div>
              <div className="ai-src">Based on: your invoice ledger · indexed customer email · recorded payments</div>
            </div>
          )}

          <div className="sec-head">
            <div>
              <h2 className="sec-title">
                Action required
                <span className="sec-badge">{actions.length}</span>
              </h2>
              <div className="sec-sub">
                {k?.customers_requiring_action ?? actions.length} accounts need attention ·{" "}
                {money(k?.cash_at_risk ?? 0)} at risk
              </div>
            </div>
            <FilterChips items={chips} />
          </div>

          <div className="card" style={{ padding: "16px 18px" }}>
            {filtered.length === 0 ? (
              <EmptyState>
                <b>Every account in this view is in good standing.</b>
                <span className="muted">
                  When a promise slips, an email bounces, or a dispute appears, the account shows up here with a
                  recommended action and a ready-to-send follow-up.
                </span>
              </EmptyState>
            ) : (
              <>
                <div className="queue-order muted small">
                  Showing {filtered.length} of {actions.length} — highest cash-at-risk first. Click an account for its
                  intelligence panel.
                </div>
                {filtered.map((item, i) => (
                  <ActionItemView
                    key={item.customer_name}
                    item={item}
                    onSelect={() => setSelected(filtered[i])}
                    onReview={() => setReviewing(item)}
                    onContacted={() => setContactNote(item)}
                    onSnooze={() => setSnoozing(item)}
                    onReactivate={() => react(item)}
                  />
                ))}
              </>
            )}
          </div>
        </div>

        <div className="stack">
          {selectedItem ? (
            <div className="intel-panel card fade-up" data-priority={selectedItem.priority}>
              <div className="intel-head">
                <div>
                  <div className="intel-name">{selectedItem.customer_name}</div>
                  <div className="intel-meta">
                    <span>{selectedItem.primary_invoice_number}</span>
                    {selectedItem.max_days_overdue > 0 && <span>{selectedItem.max_days_overdue}d overdue</span>}
                  </div>
                </div>
                <button className="intel-close" onClick={() => setSelected(null)} aria-label="close panel">
                  <X size={15} />
                </button>
              </div>
              <div className="intel-amt">{money(selectedItem.total_outstanding)}</div>

              {selectedItem.latest_signal && (
                <div className="ai-surf">
                  <span className="ai-badge">
                    <Quote size={12} /> AI insight
                  </span>
                  <p style={{ margin: "6px 0 0" }}>
                    {TYPE_LABEL[selectedItem.latest_signal.signal_type] ||
                      selectedItem.latest_signal.signal_type}{" "}
                    — {selectedItem.latest_signal.summary}
                  </p>
                </div>
              )}

              <div className="intel-block">
                <span className="ib-lab">Next action</span>
                <b>{selectedItem.action_label}</b>
                <p>{selectedItem.reason}</p>
              </div>

              {selectedItem.latest_signal?.source_email && (
                <div className="intel-block">
                  <span className="ib-lab">Source evidence</span>
                  <div className="intel-ev">
                    <Quote size={14} />
                    <span>
                      {selectedItem.latest_signal.source_email.subject || "(no subject)"} · from{" "}
                      {selectedItem.latest_signal.source_email.from_name ||
                        selectedItem.latest_signal.source_email.from_email}
                    </span>
                  </div>
                </div>
              )}

              <div className="intel-cta">
                <button className="btn" onClick={() => setReviewing(selectedItem)}>
                  <Sparkles size={14} /> Generate follow-up
                </button>
                <button className="btn ghost" onClick={() => setSnoozing(selectedItem)}>
                  Snooze until reviewed
                </button>
              </div>
            </div>
          ) : (
            !dismissedBrief &&
            brief.data && (
              <div className="brief card fade-up" onClick={dismiss}>
                <div className="brief-title">
                  <span className="ai-badge" style={{ color: "var(--purple)" }}>
                    <Sparkles size={13} /> Weekly AI brief
                  </span>
                </div>
                <div className="sec-sub" style={{ marginTop: 6, fontSize: 14, lineHeight: 1.6 }}>
                  {(brief.data.missed_payment_promises.count > 0
                    ? `${brief.data.missed_payment_promises.count} payment promise${
                        brief.data.missed_payment_promises.count === 1 ? "" : "s"
                      } missed, and `
                    : "") +
                    `${money(brief.data.new_overdue_invoices.amount)} became newly overdue.`}
                </div>
                <div className="brief-grid">
                  <div>
                    <b>{money(brief.data.expected_incoming_payments)}</b>
                    <span>expected incoming</span>
                  </div>
                  <div>
                    <b>{brief.data.missed_payment_promises.count}</b>
                    <span>promises missed</span>
                  </div>
                  <div>
                    <b>{brief.data.open_disputes.count}</b>
                    <span>open disputes</span>
                  </div>
                  <div>
                    <b>{money(brief.data.new_overdue_invoices.amount)}</b>
                    <span>newly overdue</span>
                  </div>
                </div>
                {briefPriorities.length > 0 && (
                  <div className="brief-src">
                    <b>Top priority:</b> {briefPriorities.map((p) => p.customer_name).join(", ")}
                    {briefPriorities[0] && ` — ${money(briefPriorities[0].amount)}`}.
                  </div>
                )}
                <div className="brief-cta">
                  View full report <ArrowUpRight size={12} style={{ verticalAlign: -1 }} /> · dismiss to close
                </div>
              </div>
            )
          )}

          {queue.data && queue.data.snoozed.length > 0 && (
            <div className="card">
              <h2>
                Snoozed
                <span className="count">{queue.data.snoozed.length}</span>
              </h2>
              {queue.data.snoozed.map((item) => (
                <ActionItemView
                  key={item.customer_name}
                  item={item}
                  onReview={() => setReviewing(item)}
                  onContacted={() => setContactNote(item)}
                  onSnooze={() => setSnoozing(item)}
                  onReactivate={() => react(item)}
                />
              ))}
            </div>
          )}

          <div className="card">
            <h2>How this queue is built</h2>
            <ol className="how-list">
              <li>Your invoice ledger tells us what&apos;s outstanding.</li>
              <li>Customer email tells us why it&apos;s late (dispute, missing PO, silence…).</li>
              <li>Every action has a reason and an explainable priority score.</li>
              <li>You approve anything that goes out — nothing sends itself.</li>
            </ol>
            <p className="footnote muted">
              <Link href="/reports/" prefetch={false}>Receivables intelligence</Link> for the wider picture.
            </p>
          </div>
        </div>
      </section>

      {reviewing && (
        <FollowUpComposer item={reviewing} onClose={() => setReviewing(null)} onChanged={() => queue.reload()} />
      )}
      {snoozing && (
        <SnoozeModal item={snoozing} onClose={() => setSnoozing(null)} onSnoozed={() => queue.reload()} />
      )}
      {contactNote && (
        <Modal title={`Mark contacted · ${contactNote.customer_name}`} onClose={() => setContactNote(null)}>
          <div className="field">
            <label htmlFor="contact-note">Note (shown in customer history)</label>
            <input
              id="contact-note"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="Called them — accounting is reviewing the invoice."
            />
          </div>
          <div className="row-btns">
            <button className="btn" disabled={busy} onClick={() => confirmContacted(contactNote)}>
              Confirm contacted
            </button>
            <button className="btn ghost" onClick={() => setContactNote(null)}>
              Cancel
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}