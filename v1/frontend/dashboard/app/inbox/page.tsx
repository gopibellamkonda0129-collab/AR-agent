"use client";

import { useMemo, useState } from "react";
import {
  fetchAccounts,
  fetchActionQueue,
  fetchEmails,
  fetchSignals,
  syncAccount,
  type ActionItem,
  type Email,
  type Signal,
} from "../../lib/api";
import {
  ConnectPanel,
  FollowUpComposer,
  Kpi,
  PageTitle,
  Spinner,
  initials,
  money,
  timeAgo,
  usePolling,
} from "../../lib/components";
import { Refresh, Send, Sparkles, X } from "../../lib/icons";

export default function InboxPage() {
  const accounts = usePolling(fetchAccounts, 20000);
  const emails = usePolling(() => fetchEmails(accounts.data?.[0]?.id), 30000);
  const signals = usePolling(fetchSignals, 30000);
  const queue = usePolling(fetchActionQueue, 30000);
  const [syncBusy, setSyncBusy] = useState(false);
  const [syncMsg, setSyncMsg] = useState("");
  const [viewing, setViewing] = useState<Email | null>(null);
  const [filter, setFilter] = useState("");
  const [composeFor, setComposeFor] = useState<string | null>(null);

  const selected = accounts.data?.[0];

  const onSync = async () => {
    if (!selected) return;
    setSyncBusy(true);
    setSyncMsg("");
    try {
      const r = await syncAccount(selected.id);
      setSyncMsg(`Synced ${selected.email}: ${r.new_emails} new email${r.new_emails === 1 ? "" : "s"}, ${r.new_signals} new signal${r.new_signals === 1 ? "" : "s"}.`);
      accounts.reload();
      emails.reload();
      signals.reload();
      queue.reload();
    } catch (e) {
      setSyncMsg(String(e));
    } finally {
      setSyncBusy(false);
    }
  };

  const seenSubjects = useMemo(() => {
    const m = new Map<string, Email>();
    (emails.data ?? []).forEach((e) => {
      const prev = m.get(e.subject);
      if (!prev || e.received_at > prev.received_at) m.set(e.subject, e);
    });
    return Array.from(m.values());
  }, [emails.data]);

  const signalByMsgId = useMemo(() => {
    const m = new Map<string, Signal>();
    (signals.data ?? []).forEach((s) => s.message_id && m.set(s.message_id, s));
    return m;
  }, [signals.data]);

  const customerByEmail = useMemo(() => {
    const m = new Map<string, { name: string; action?: ActionItem }>();
    (queue.data?.actions ?? []).forEach((a) => m.set(a.customer_email.toLowerCase(), { name: a.customer_name, action: a }));
    (signals.data ?? []).forEach((s) => {
      const em = (s.customer_email || s.from_email || "").toLowerCase();
      if (em && !m.has(em)) m.set(em, { name: s.customer_name });
    });
    return m;
  }, [queue.data, signals.data]);

  const filtered = seenSubjects.filter((e) =>
    filter ? e.subject.toLowerCase().includes(filter.toLowerCase()) || (e.from_email || "").toLowerCase().includes(filter.toLowerCase()) : true
  );

  const openSignals = (signals.data ?? []).filter((s) => !s.resolved).length;
  const promiseSignals = (signals.data ?? []).filter((s) => !s.resolved && s.signal_type === "payment_promise").length;
  const draftsReady = (queue.data?.actions ?? []).filter((a) => a.action !== "no_action" && a.open_signal_count > 0).length;

  const meta = viewing ? signalByMsgId.get(viewing.message_id || "") : undefined;
  const viewedCustomer = viewing ? customerByEmail.get((viewing.from_email || "").toLowerCase()) : undefined;

  return (
    <div className="page-body">
      <PageTitle title="Inbox" sub="Customer email the AI has read. It looks for payment promises, disputes, missing invoices, and questions." eyebrow="Inbox" />

      {accounts.data && accounts.data.length === 0 && (
        <div className="card">
          <div className="hd-inline">
            <h2>Connect an inbox</h2>
            <span className="count">0</span>
          </div>
          <ConnectPanel onConnected={() => accounts.reload()} />
        </div>
      )}

      {selected && (
        <div className="card inbox-ctl">
          <div className="ctl-row">
            <span className={`conn ${selected.last_sync_status === "ok" ? "live" : ""}`}>
              <span className="dot" />
              <b>{selected.email}</b>
              <span className="muted">
                {selected.provider === "demo" ? "demo workspace" : selected.provider}
                {selected.last_sync_at && <> · synced {timeAgo(selected.last_sync_at)}</>}
              </span>
            </span>
            <button className="btn ghost small" disabled={syncBusy} onClick={onSync}>
              {syncBusy ? <Spinner /> : <Refresh size={13} />}
              Sync now
            </button>
          </div>
          <input className="search" placeholder="Filter by subject or sender…" value={filter} onChange={(e) => setFilter(e.target.value)} />
          {syncMsg && <div className="muted small" style={{ marginTop: 8 }}>{syncMsg}</div>}
        </div>
      )}

      <div className="ai-panel">
        <div className="ai-title">
          <Sparkles size={15} /> AI Assistant <span>reads {seenSubjects.length} email{seenSubjects.length === 1 ? "" : "s"}</span>
        </div>
        <div className="ai-cols">
          <div className="ai-item top">
            <div className="ai-label">Open signals detected</div>
            <div className="ai-value">{openSignals}</div>
            <div className="ai-note">{promiseSignals} payment promise{promiseSignals === 1 ? "" : "s"} among them</div>
          </div>
          <div className="ai-item top">
            <div className="ai-label">Follow-up drafts ready</div>
            <div className="ai-value">{draftsReady}</div>
            <div className="ai-note">accounts with a signal already in the action queue</div>
          </div>
          <div className="ai-item top">
            <div className="ai-label">Real customer mail</div>
            <div className="ai-value">{(signals.data ?? []).filter((s) => (s.customer_email || "").toLowerCase() && !s.resolved).length}</div>
            <div className="ai-note">with an open signal, from live data</div>
          </div>
        </div>
        <div className="ai-foot">
          Every email is matched to signals by message id; nothing is sent without your approval.
        </div>
      </div>

      <section className="kpis">
        <Kpi label="Emails read" value={String(seenSubjects.length)} sub="unique subjects" />
        <Kpi label="Open signals" value={String(openSignals)} tone="violet" sub="across the workspace" />
        <Kpi label="Follow-ups ready" value={String(draftsReady)} tone="info" sub="drafts you can send" />
      </section>

      <div className="card">
        <h2>
          Messages
          <span className="count">{filtered.length}</span>
        </h2>
        {emails.loading && !emails.data ? (
          <div className="sk-list">
            <SkeletonInbox />
          </div>
        ) : filtered.length === 0 ? (
          <div className="empty-hint">
            <b>Nothing here yet.</b>
            <div className="muted">Connect an inbox above and sync — analyzed messages land here.</div>
          </div>
        ) : (
          <div>
            {filtered.map((e) => {
              const isNotice = e.subject.startsWith("[AR]");
              const sig = signalByMsgId.get(e.message_id || "");
              return (
                <div key={e.id} className={`email clickable${isNotice ? "" : " real"}`} onClick={() => setViewing(e)}>
                  <span className={`avatar ${isNotice ? "green" : "violet"}`}>{initials(e.from_email || e.from_name || "?")}</span>
                  <div className="e-info">
                    <div className="e-subj">
                      {isNotice ? <span className="badge b-type" style={{ marginRight: 6 }}>AR</span> : null}
                      {e.subject}
                      {sig && !sig.resolved && <span className="dot-signal" />}
                    </div>
                    <div className="e-from">{e.from_email}</div>
                    <div className="e-tags">
                      {sig ? (
                        <span className={`badge ${sig.resolved ? "b-state-upcoming" : `b-pri-${sig.priority}`}`}>{sig.resolved ? "resolved" : sig.signal_type}</span>
                      ) : null}
                    </div>
                  </div>
                  <span className="e-when">{timeAgo(e.received_at || e.created_at)}</span>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {viewing && (
        <div className="drawer-wrap">
          <div className="drawer-backdrop" onClick={() => setViewing(null)} />
          <aside className="drawer wide-2" role="dialog" aria-label={viewing.subject}>
            <div className="drawer-head">
              <div className="ai-read">
                <Sparkles size={14} /> AI-read
              </div>
              <button className="d-close" onClick={() => setViewing(null)} aria-label="close">
                <X size={18} />
              </button>
            </div>
            <div className="drawer-body">
              <div>
                <div className="muted small">{viewing.from_email} · {viewing.received_at || viewing.created_at}</div>
                <h3 style={{ marginTop: 6 }}>{viewing.subject}</h3>
              </div>

              {meta && (
                <div className={`sig-box ${meta.resolved ? "done" : ""}`}>
                  <b>{meta.resolved ? "Resolved" : "Signal detected"}: {meta.signal_type}</b>
                  <p>{meta.summary}</p>
                  {meta.promised_date && (
                    <div className="muted small">promised {meta.promised_date}{meta.promised_amount !== null && meta.promised_amount !== undefined ? ` · ${money(meta.promised_amount)}` : ""}</div>
                  )}
                </div>
              )}

              <pre className="mail-body">{viewing.body}</pre>

              {viewedCustomer?.action && viewedCustomer.action.action !== "no_action" && (
                <div className="d-note">
                  <Send size={14} />
                  <div>
                    <b>Recommended next step</b>
                    <p className="muted small" style={{ margin: "4px 0 0" }}>
                      {viewedCustomer.action.action_label} — {viewedCustomer.action.reason}
                    </p>
                  </div>
                </div>
              )}
            </div>
            <div className="drawer-foot">
              {viewedCustomer?.action && viewedCustomer.action.action !== "no_action" && (
                <button className="btn b-pri" onClick={() => setComposeFor(viewedCustomer!.name)}>
                  <Send size={14} /> Generate response
                </button>
              )}
              <button className="btn ghost" onClick={() => setViewing(null)}>
                Close
              </button>
            </div>
          </aside>
        </div>
      )}

      {composeFor && queue.data && (() => {
        const item = queue.data.actions.find((a) => a.customer_name === composeFor);
        return item ? <FollowUpComposer item={item} onClose={() => setComposeFor(null)} /> : null;
      })()}
    </div>
  );
}

function SkeletonInbox() {
  return (
    <>
      {[...Array(5)].map((_, i) => (
        <div key={i} className="email" style={{ pointerEvents: "none" }}>
          <div className="skel" style={{ width: 34, height: 34, borderRadius: "50%" }} />
          <div className="e-info">
            <div className="skel" style={{ height: 13, width: "58%" }} />
            <div className="skel" style={{ height: 11, width: "35%", marginTop: 6 }} />
          </div>
        </div>
      ))}
    </>
  );
}