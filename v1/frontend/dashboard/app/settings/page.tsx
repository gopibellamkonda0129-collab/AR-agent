"use client";

import Link from "next/link";
import { fetchAccounts, fetchHealth, fetchInvoices } from "../../lib/api";
import { ConnectPanel, PageTitle, Spinner, timeAgo, usePolling } from "../../lib/components";

export default function SettingsPage() {
  const health = usePolling(fetchHealth, 30000);
  const accounts = usePolling(fetchAccounts, 20000);
  const invoices = usePolling(fetchInvoices, 30000);

  const invoiceCount = invoices.data?.count ?? 0;

  return (
    <div className="page-body">
      <PageTitle title="Settings" sub="Your workspace, email connection, and how the assistant behaves." eyebrow="Workspace" />

      <section className="card">
        <h2>Email connection</h2>
        {accounts.data && accounts.data.length === 0 ? (
          <div className="empty-hint">
            <b>No mailbox connected yet.</b>
            <div className="muted">
              Connect the mailbox your customers write to and the assistant will read it to find out who owes you and why they&apos;re late.
            </div>
          </div>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr><th>Mailbox</th><th>Sync status</th></tr>
              </thead>
              <tbody>
                {(accounts.data ?? []).map((a) => (
                  <tr key={a.id}>
                    <td>{a.email}</td>
                    <td>
                      <span className={`conn ${a.last_sync_status === "ok" ? "live" : ""}`}>
                        <span className="dot" />
                        {a.last_sync_status === "ok" ? `synced ${timeAgo(a.last_sync_at)}` : a.last_sync_status || "never synced"}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <ConnectPanel onConnected={() => accounts.reload()} />

        <details className="advanced">
          <summary>Advanced email configuration (IMAP)</summary>
          <p className="muted">
            Most mailboxes work with an app password over IMAP. Use the mailbox address itself — never a personal
            login. For Gmail, create an app password in your Google account (two-step verification required).
          </p>
          <p className="muted small">
            The assistant reads email read-only to detect payment promises, disputes, missing invoices, and other
            signals. It never sends anything without your approval.
          </p>
        </details>
      </section>

      <div className="grid-main">
        <div className="card">
          <h2>Workspace</h2>
          <div className="ws-row">
            <div className="ws-label">Invoices in your ledger</div>
            <div className="ws-value">{invoiceCount}</div>
          </div>
          <div className="ws-row">
            <div className="ws-label">Sample data</div>
            <div className="ws-value">{health.data?.demo ? "active" : "off"}</div>
          </div>
          <div className="muted small">
            New workspaces start with labeled sample accounts so you can see the assistant working immediately.
            Import your own invoices any time — sample data can be cleared from the Invoices page.
          </div>
          <div className="row-btns" style={{ marginTop: 12 }}>
            <Link href="/invoices/" className="btn">Upload invoices</Link>
          </div>
        </div>

        <div className="card">
          <h2>What the assistant does &amp; doesn&apos;t do</h2>
          <ul className="how-list">
            <li><b>It reads</b> your invoices and the customer&apos;s own email — nothing more.</li>
            <li><b>It explains why</b> each customer needs a follow-up, with the source email you can expand and check.</li>
            <li><b>It drafts</b> follow-ups using only real amounts, invoice numbers, and quoted phrases.</li>
            <li><b>Never auto-sends.</b> Every email needs your explicit &quot;Approve &amp; Send&quot; click.</li>
            <li><b>Never invents facts.</b> Unconfirmed cash is labeled unconfirmed, not padded into your forecast.</li>
          </ul>
        </div>
      </div>

      <div className="card">
        <h2>Security &amp; approvals</h2>
        <ul className="how-list">
          <li><b>Nothing sends itself.</b> Every message is drafted for you to review, edit, and approve first.</li>
          <li><b>Read-only mailbox access.</b> The assistant analyzes incoming customer mail; it cannot read unrelated mail.</li>
          <li><b>You stay in control.</b> Snooze or remove any account from the queue with one click.</li>
        </ul>
      </div>

      <p className="footnote">
        Developer diagnostics (API keys, storage, model status) live on the System page in the sidebar.
      </p>
    </div>
  );
}