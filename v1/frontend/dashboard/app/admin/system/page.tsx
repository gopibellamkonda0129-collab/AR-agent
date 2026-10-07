"use client";

import { fetchAccounts, fetchHealth, fetchMoneyRecovered } from "../../../lib/api";
import { PageTitle, Spinner, timeAgo, usePolling, money } from "../../../lib/components";

export default function AdminSystemPage() {
  const health = usePolling(fetchHealth, 15000);
  const accounts = usePolling(fetchAccounts, 30000);
  const recovered = usePolling(fetchMoneyRecovered, 30000);

  return (
    <div className="page-body">
      <PageTitle
        title="System"
        sub="Backend health and diagnostics. This is for setup and troubleshooting — not part of your daily workflow."
        eyebrow="Support"
      />

      <section className="db-card card">
        <h2>System status</h2>
        {health.loading && !health.data ? (
          <Spinner />
        ) : health.data ? (
          <div className="status-grid">
            <div className={`st st-${health.data.ok ? "ok" : "bad"}`}>
              <span className="dot" />
              <div>
                <b>API</b>
                <span className="muted small">{health.data.ok ? "reachable" : "unreachable"}</span>
              </div>
            </div>
            <div className={`st ${health.data.demo ? "st-warn" : "st-ok"}`}>
              <span className="dot" />
              <div>
                <b>Workspace mode</b>
                <span className="muted small">
                  {health.data.demo
                    ? "in-memory — resets on restart (sample data preloaded)"
                    : "persistent storage enabled"}
                </span>
              </div>
            </div>
            <div className={`st ${health.data.supabase ? "st-ok" : "st-warn"}`}>
              <span className="dot" />
              <div>
                <b>Storage backend</b>
                <span className="muted small">{health.data.supabase ? "connected" : "not configured — using in-memory store"}</span>
              </div>
            </div>
            <div className={`st ${health.data.llm ? "st-ok" : "st-warn"}`}>
              <span className="dot" />
              <div>
                <b>AI model</b>
                <span className="muted small">
                  {health.data.llm ? "online — richer signal summaries" : "offline — rules-based analysis still works"}
                </span>
              </div>
            </div>
            <div className="st st-ok">
              <span className="dot" />
              <div>
                <b>Auto sync</b>
                <span className="muted small">every {health.data.sync_interval_seconds}s while the backend runs</span>
              </div>
            </div>
          </div>
        ) : (
          <div className="banner err">Could not reach the backend at :8000.</div>
        )}
        <p className="footnote">
          <b>Email sending.</b> This backend never sends email unless the operator runs it with
          <code> AR_ALLOW_SEND=1</code> and real SMTP credentials configured. Approvals are recorded either way.
        </p>
      </section>

      <div className="card">
        <h2>Connected mailboxes</h2>
        {(accounts.data ?? []).length === 0 ? (
          <div className="empty-hint"><b>No mailbox connected.</b><div className="muted">Connect one from Settings → Email connection.</div></div>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr><th>Provider</th><th>Email</th><th>Status</th><th>Last sync</th></tr>
              </thead>
              <tbody>
                {(accounts.data ?? []).map((a) => (
                  <tr key={a.id}>
                    <td>{a.provider}</td>
                    <td>{a.email}</td>
                    <td>
                      <span className={`conn ${a.last_sync_status === "ok" ? "live" : ""}`}>
                        <span className="dot" />
                        {a.last_sync_status === "ok" ? "ok" : a.last_sync_status || "never synced"}
                      </span>
                    </td>
                    <td className="muted">{timeAgo(a.last_sync_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="card">
        <h2>Recovery ledger</h2>
        {recovered.data ? (
          <div className="g-sums">
            <div>Total recovered: <b>{money(recovered.data.total)}</b></div>
            <div>{recovered.data.this_month_label}: <b>{money(recovered.data.this_month)}</b></div>
            <div>Last month: <b>{money(recovered.data.last_month)}</b></div>
          </div>
        ) : (
          <Spinner />
        )}
        <p className="footnote muted">
          Money recovered reflects only payments you mark as received against an invoice — it is never estimated.
        </p>
      </div>
    </div>
  );
}