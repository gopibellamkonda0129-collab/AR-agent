"use client";

import { useMemo, useState } from "react";
import { fetchCashRisk, type CashRiskRow } from "../../lib/api";
import { PageTitle, Skeleton, Spinner, money, usePolling } from "../../lib/components";
import { AlertTriangle, Clock, Target, TrendUp } from "../../lib/icons";

const BAND_TONE: Record<string, string> = {
  blocked: "band-blocked",
  critical: "band-critical",
  late: "band-late",
  overdue: "band-overdue",
  due_soon: "band-due",
  open: "band-open",
};

const RDY_VERDICT_TONE: Record<string, string> = {
  READY: "rdy-ready",
  CONFIRM: "rdy-confirm",
  "NOT READY": "rdy-notready",
  UNKNOWN: "rdy-unknown",
};

const RELIABILITY_TONE: Record<string, string> = {
  excellent: "rel-exc",
  good: "rel-good",
  average: "rel-avg",
  low: "rel-low",
  unknown: "rel-na",
};

function SortToggle({ sort, onChange }: { sort: "weight" | "agent"; onChange: (s: "weight" | "agent") => void }) {
  return (
    <span className="sort-toggle" role="group" aria-label="Sort cash at risk">
      <button className={`${sort === "weight" ? "on" : ""}`} onClick={() => onChange("weight")} title="Weighted by band: blocked & extended-overdue first, then amount × days">
        By weight
      </button>
      <button className={`${sort === "agent" ? "on" : ""}`} onClick={() => onChange("agent")} title="The order the AR agent would work the list (decision order + owner)">
        By agent
      </button>
    </span>
  );
}

export default function CashAtRiskPage() {
  const [sort, setSort] = useState<"weight" | "agent">("weight");
  const { data, loading, error, reload } = usePolling(() => fetchCashRisk(sort), 30000);
  const [bandFilter, setBandFilter] = useState<string>("all");

  const onSort = (s: "weight" | "agent") => {
    if (s === sort) return;
    setSort(s);
    reload();
  };

  const rows = useMemo(() => {
    const r = data?.rows ?? [];
    if (bandFilter === "all") return r;
    return r.filter((x) => x.band === bandFilter);
  }, [data, bandFilter]);

  const totals = data?.totals;
  const byBand = data?.by_band ?? [];

  return (
    <div className="page-body">
      <PageTitle
        title="Cash at Risk"
        sub="Every open invoice, ranked by cash exposure — blocked cash and extended-overdue accounts first."
        eyebrow="Focus"
        right={<a href="/invoices/" className="btn small ghost">View all invoices</a>}
      />
      {error && <div className="banner err">{error}</div>}
      {loading && !data ? (
        <Skeleton lines={3} h={60} br={12} />
      ) : !data ? (
        <Spinner />
      ) : (
        <>
          <div className="kpi-row">
            <div className="kpi">
              <div className="k-label"><Target size={14} /> Blocked cash</div>
              <div className="k-num">{money(totals?.blocked_cash)}</div>
              <div className="k-sub">{totals?.blocked_invoices} invoice{totals?.blocked_invoices === 1 ? "" : "s"} held in their process</div>
            </div>
            <div className="kpi">
              <div className="k-label"><AlertTriangle size={14} /> Critical overdue</div>
              <div className="k-num">{money(totals?.critical_amount)}</div>
              <div className="k-sub">{totals?.critical_invoices} invoice{totals?.critical_invoices === 1 ? "" : "s"} 30+ days past due</div>
            </div>
            <div className="kpi">
              <div className="k-label"><Clock size={14} /> Overdue</div>
              <div className="k-num">{money(totals?.overdue_amount)}</div>
              <div className="k-sub">{totals?.overdue_invoices} overdue invoice{totals?.overdue_invoices === 1 ? "" : "s"}</div>
            </div>
            <div className="kpi">
              <div className="k-label"><TrendUp size={14} /> Weighted risk</div>
              <div className="k-num">{money(totals?.weighted_risk)}</div>
              <div className="k-sub">amount × days overdue (all open)</div>
            </div>
          </div>

          <div className="band-filters">
            <button className={`f-chip${bandFilter === "all" ? " active" : ""}`} onClick={() => setBandFilter("all")}>
              All <b>{totals?.open_invoices ?? 0}</b>
            </button>
            {byBand.map((b) => (
              <button
                key={b.band}
                className={`f-chip${bandFilter === b.band ? " active" : ""}`}
                onClick={() => setBandFilter(b.band)}
              >
                {b.label} <b>{b.count}</b>
              </button>
            ))}
          </div>

          <div className="card">
            <div className="hd-inline">
              <h2>Open invoices<span className="count">{rows.length}</span></h2>
              <div className="row-btns" style={{ marginTop: 0 }}>
                <SortToggle sort={sort} onChange={onSort} />
                <span className="muted small" title={sort === "weight" ? "Blocked cash and extended-overdue first, scaled by amount" : "The order the AR agent actually works the list"}>
                  {sort === "weight" ? "weighted: blocked + extended-overdue first" : "agent order: decision + owner"}
                </span>
              </div>
            </div>
            {rows.length === 0 ? (
              <div className="empty-hint"><b>No invoices in this band.</b></div>
            ) : (
              <div className="risk-table">
                <div className="risk-row risk-header">
                  <span className="rt-inv">Invoice</span>
                  <span className="rt-cust">Customer</span>
                  <span className="rt-amt">Amount</span>
                  <span className="rt-due">Due / overdue</span>
                  <span className="rt-band">Band</span>
                  <span className="rt-rdy">Readiness</span>
                  <span className="rt-rel">Reliability</span>
                  <span className="rt-own">Owner</span>
                  <span className="rt-rank">Agent rank</span>
                  <span className="rt-risk">Risk (amt × days)</span>
                  <span className="rt-act">Next step</span>
                </div>
                {rows.map((r) => (
                  <div key={r.invoice_number} className={`risk-row ${BAND_TONE[r.band] || ""}`}>
                    <span className="rt-inv"><b>{r.invoice_number}</b></span>
                    <span className="rt-cust">{r.customer_name}</span>
                    <span className="rt-amt">{money(r.amount_outstanding)}</span>
                    <span className="rt-due">
                      {r.days_overdue > 0
                        ? <span className="t-red">{r.days_overdue}d overdue</span>
                        : r.pre_due
                          ? <span className="t-amber">due soon — readiness check</span>
                          : <span className="t-green">on time</span>}
                    </span>
                    <span className={`rt-band ex-badge ${BAND_TONE[r.band] || ""}`}>{r.band_label}</span>
                    <span className="rt-rdy">
                      {r.readiness_verdict ? (
                        <span className={`rdn-chip ${RDY_VERDICT_TONE[r.readiness_verdict] || "rdy-unknown"}`} title={r.readiness_verdict}>
                          {r.readiness_label || r.readiness_verdict}
                        </span>
                      ) : <span className="muted">—</span>}
                    </span>
                    <span className="rt-rel">
                      {r.reliability ? (
                        <span className={`rel-chip ${RELIABILITY_TONE[(r.reliability || "").toLowerCase()] || "rel-na"}`}>{r.reliability}</span>
                      ) : <span className="muted">—</span>}
                    </span>
                    <span className="rt-own">{r.owner || <span className="muted">—</span>}</span>
                    <span className="rt-rank num">{r.agent_rank > 0 ? `#${r.agent_rank}` : "—"}</span>
                    <span className="rt-risk">{money(r.risk_weight)}</span>
                    <span className="rt-act muted small">{r.next_action || r.reason}</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {data.customers.length > 0 && (
            <div className="card" style={{ marginTop: 16 }}>
              <div className="hd-inline">
                <h2>By customer</h2>
              </div>
              <div className="risk-table">
                <div className="risk-row risk-header">
                  <span className="rt-cust">Customer</span>
                  <span className="rt-inv">Invoices</span>
                  <span className="rt-amt">Outstanding</span>
                  <span className="rt-due">Overdue</span>
                  <span className="rt-risk">Worst days</span>
                  <span className="rt-band">Blockers</span>
                </div>
                {data.customers.map((c) => (
                  <div key={c.customer_name} className="risk-row">
                    <span className="rt-cust"><b>{c.customer_name}</b></span>
                    <span className="rt-inv">{c.invoice_count}</span>
                    <span className="rt-amt">{money(c.outstanding)}</span>
                    <span className="rt-due">{money(c.overdue_amount)}</span>
                    <span className="rt-risk">{c.worst_days_overdue > 0 ? `${c.worst_days_overdue}d` : "—"}</span>
                    <span className="rt-band">{c.blockers.length > 0 ? c.blockers.join(", ") : "—"}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
