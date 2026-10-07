"use client";

import { fetchForecast } from "../../lib/api";
import { AnimatedNumber, Kpi, PageTitle, Spinner, money, usePolling } from "../../lib/components";
import { ColumnChart } from "../../lib/charts";
import { AlertCircle, CheckCircle } from "../../lib/icons";

export default function ForecastPage() {
  const f = usePolling(fetchForecast, 60000);

  const b = (key: string) => f.data?.buckets.find((x) => x.key === key);
  const today = b("expected_today")?.amount ?? 0;
  const week = today + (b("expected_this_week")?.amount ?? 0);
  const month = week + (b("expected_next_30_days")?.amount ?? 0);
  const later = b("expected_later")?.amount ?? 0;
  const overdueUn = b("overdue_unconfirmed")?.amount ?? 0;
  const dueNoDate = b("due_no_confirmed_date")?.amount ?? 0;
  const confirmed = (f.data?.total_cash ?? 0) - overdueUn - dueNoDate;

  const cum = () => [
    { label: "Today", amount: today, tone: "linear-gradient(180deg,var(--green),#15805f)" },
    { label: "7 days", amount: week, tone: "linear-gradient(180deg,var(--blue),#3a4fd8)" },
    { label: "30 days", amount: month, tone: "linear-gradient(180deg,var(--violet),#5a4dbd)" },
  ];

  const groups = [
    {
      key: "confirmed",
      title: "CONFIRMED",
      sub: "customer promised an exact date — counts toward your confirmed total",
      cls: "g-confirmed",
      bucketKeys: ["expected_today", "expected_this_week", "expected_next_30_days", "expected_later"],
    },
    {
      key: "expected",
      title: "EXPECTED",
      sub: "not yet due, no promise recorded — an estimate, not a commitment",
      cls: "g-expected",
      bucketKeys: ["due_no_confirmed_date"],
    },
    {
      key: "risk",
      title: "AT RISK",
      sub: "overdue with no payment promise — belongs in your action queue",
      cls: "g-risk",
      bucketKeys: ["overdue_unconfirmed"],
    },
  ];

  return (
    <div className="page-body">
      <PageTitle
        title="Cash forecast"
        sub="Only explicit customer promises count toward expected cash. Everything else is flagged as unconfirmed — no inventions."
        eyebrow="Plan ahead"
      />

      {f.loading && !f.data ? (
        <div className="full-center">
          <Spinner />
          <span className="muted">Building forecast…</span>
        </div>
      ) : (
        <>
          <section className="hero-card">
            <div className="hero-grid">
              <div className="hero-main">
                <div className="hero-kicker">
                  <span className="ring-mini" /> Confirmed expected cash
                </div>
                <div className="hero-fig" style={{ color: "var(--green)" }}>
                  <AnimatedNumber value={confirmed} format={(n) => money(n)} duration={900} />
                </div>
                <div className="muted small">from customer promises only — no guesses</div>
                {f.data ? (
                  <div style={{ marginTop: 8 }}>
                    <ColumnChart height={92} items={cum()} />
                  </div>
                ) : null}
              </div>

              <div className="hero-metric m-amber" style={{ alignItems: "center", justifyContent: "center" }}>
                <div className="hmi">
                  <span className="ic">
                    <AlertCircle size={19} />
                  </span>{" "}
                  Unconfirmed at risk
                </div>
                <div className="hmv">
                  <AnimatedNumber value={overdueUn} format={(n) => money(n)} duration={900} />
                </div>
                <div className="hms">overdue, no payment promise — your action queue</div>
              </div>

              <div className="hero-metric">
                <div className="hmi">
                  <span className="ic">
                    <CheckCircle size={19} />
                  </span>{" "}
                  Not yet due, no date
                </div>
                <div className="hmv">
                  <AnimatedNumber value={dueNoDate} format={(n) => money(n)} duration={900} />
                </div>
                <div className="hms">working capital — no chasing required</div>
              </div>
            </div>
          </section>

          <section className="kpis">
            <Kpi label="Confirmed expected" value={money(confirmed)} tone="green" sub="from customer promises only" />
            <Kpi label="Today" value={money(today)} sub="promised for today" />
            <Kpi label="This week" value={money(week)} tone="amber" sub="cumulative, next 7 days" />
            <Kpi label="Next 30 days" value={money(month)} tone="violet" sub="cumulative, with a promise date" />
          </section>

          <div className="fc-note muted small">
            Expected values are estimates based on invoice and payment signals. Only explicit promise dates count as
            confirmed — nothing is invented.
          </div>

          {groups.map((g) => {
            const members = (f.data?.buckets ?? []).filter((bk) => g.bucketKeys.includes(bk.key));
            if (members.length === 0) return null;
            const gTotal = members.reduce((s, m) => s + m.amount, 0);
            return (
              <div key={g.key} className={`card forecast-group ${g.cls}`}>
                <div className="fg-head">
                  <div>
                    <h2 className="fg-title">{g.title}</h2>
                    <div className="fg-sub muted small">{g.sub}</div>
                  </div>
                  <div className="fg-total">
                    <b>{money(gTotal)}</b>
                    <span className="muted small">total</span>
                  </div>
                </div>
                <div className="forecast-bars">
                  {members.map((bk) => {
                    const max = Math.max(...(f.data?.buckets ?? []).map((x) => x.amount), 1);
                    const pct = Math.max(4, (bk.amount / max) * 100);
                    const unconfirm = bk.source === "ledger";
                    return (
                      <div key={bk.key} className="fb">
                        <div className="fb-top">
                          <span>{bk.label}</span>
                          <b className={unconfirm ? "t-amber" : "t-green"}>{money(bk.amount)}</b>
                        </div>
                        <div className="fb-bar">
                          <div style={{ width: `${pct}%` }} className={unconfirm ? "muted" : ""} />
                        </div>
                        <div className="fb-src muted small">{bk.source}</div>
                        {bk.items.length > 0 && (
                          <div className="fb-items">
                            {bk.items.map((it, i) => (
                              <div key={i} className="fb-item">
                                <span>{it.customer_name}</span>
                                <span className="fb-item-amt">{money(it.amount)}</span>
                                <span className="muted small">{it.date || "no date"}</span>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })}

          <div className="card">
            <h2>How to read this</h2>
            <ul className="how-list">
              <li>
                <b>CONFIRMED</b> — the customer said, in email, that they&apos;d pay by a date. The exact amount comes
                from your invoice ledger, not a guess. Today + 7 days + 30 days + later = your confirmed total.
              </li>
              <li>
                <b>EXPECTED</b> — invoices not yet due with no promise recorded. Likely cash, but nobody has said when.
                This is an estimate based on your invoices, not a commitment.
              </li>
              <li>
                <b>AT RISK</b> — invoices past due with no payment promise. These belong in your action queue and are
                worth chasing first.
              </li>
            </ul>
          </div>
        </>
      )}
    </div>
  );
}