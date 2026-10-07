"use client";

import { useMemo, useState } from "react";
import { fetchActionQueue, fetchPromises, type ActionItem, type PromiseRow } from "../../lib/api";
import { CalendarChip, FollowUpComposer, Kpi, Modal, PageTitle, Spinner, money, usePolling } from "../../lib/components";
import { Eye } from "../../lib/icons";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

const dueText = (p: PromiseRow) => {
  const rel = Math.abs(p.days_until ?? 0);
  return p.status === "overdue" ? `${rel}d ago` : p.status === "due_today" ? "today" : `in ${rel}d`;
};

const chipFor = (p: PromiseRow) => {
  const d = p.promised_date ? new Date(p.promised_date) : null;
  return (
    <CalendarChip
      when={{
        day: d ? d.getDate() : p.days_until ?? 0,
        month: d ? MONTHS[d.getMonth()] : "",
        overdue: p.status === "overdue",
        today: p.status === "due_today",
      }}
    />
  );
};

export default function PromisesPage() {
  const promises = usePolling(fetchPromises, 20000);
  const queue = usePolling(fetchActionQueue, 20000);
  const [reviewing, setReviewing] = useState<ActionItem | null>(null);
  const [email, setEmail] = useState<{ subject: string; body: string } | null>(null);

  const actionFor = (name: string): ActionItem | undefined =>
    queue.data?.actions.find((a) => a.customer_name === name);

  const groups = useMemo(
    () => ({
      overdue: (promises.data ?? []).filter((p) => p.status === "overdue" && p.days_until !== null),
      today: (promises.data ?? []).filter((p) => p.status === "due_today"),
      upcoming: (promises.data ?? []).filter((p) => p.status === "upcoming"),
    }),
    [promises.data]
  );

  return (
    <div className="page-body">
      <PageTitle
        title="Payment promises"
        sub="Explicit 'we will pay' statements from customer email — tracked to the date and followed up automatically if missed."
        eyebrow="Plan ahead"
      />

      {promises.loading && !promises.data ? (
        <div className="full-center">
          <Spinner />
          <span className="muted">Loading promises…</span>
        </div>
      ) : (
        <>
          <section className="kpis">
            <Kpi label="Missed" value={String(groups.overdue.length)} tone="red" sub={money(groups.overdue.reduce((s, p) => s + (p.promised_amount || 0), 0))} />
            <Kpi label="Due today" value={String(groups.today.length)} tone="amber" sub={money(groups.today.reduce((s, p) => s + (p.promised_amount || 0), 0))} />
            <Kpi label="Upcoming" value={String(groups.upcoming.length)} tone="green" sub={money(groups.upcoming.reduce((s, p) => s + (p.promised_amount || 0), 0))} />
            <Kpi label="Promised total" value={money((promises.data ?? []).reduce((s, p) => s + (p.promised_amount || 0), 0))} sub="across every status" />
          </section>

          {promises.data && promises.data.length === 0 ? (
            <div className="card">
              <div className="empty-hint">
                <b>No payment promises detected yet.</b>
                <div className="muted">
                  The AI extracts promises like <em>&quot;we will wire it by Friday&quot;</em> from customer email and tracks them here.
                  Sync your inbox to see them.
                </div>
              </div>
            </div>
          ) : (
            <>
              <PromiseGroup label="Missed" tone="red" title="Missed their word — chase today" items={groups.overdue} actionFor={actionFor} onReview={(a) => setReviewing(a)} onShowEmail={setEmail} />
              <PromiseGroup label="Due today" tone="amber" title="Check whether payment landed" items={groups.today} actionFor={actionFor} onReview={(a) => setReviewing(a)} onShowEmail={setEmail} />
              <PromiseGroup label="Upcoming" tone="green" title="On the calendar — monitor" items={groups.upcoming} actionFor={actionFor} onReview={(a) => setReviewing(a)} onShowEmail={setEmail} />
            </>
          )}
        </>
      )}

      {reviewing && <FollowUpComposer item={reviewing} onClose={() => setReviewing(null)} onChanged={() => queue.reload()} />}
      {email && (
        <Modal title={email.subject} onClose={() => setEmail(null)} wide>
          <pre className="mail-body">{email.body}</pre>
        </Modal>
      )}
    </div>
  );
}

function PromiseGroup({
  label,
  tone,
  title,
  items,
  actionFor,
  onReview,
  onShowEmail,
}: {
  label: string;
  tone: string;
  title: string;
  items: PromiseRow[];
  actionFor: (name: string) => ActionItem | undefined;
  onReview: (a: ActionItem) => void;
  onShowEmail: (email: { subject: string; body: string }) => void;
}) {
  const sums = items.reduce((s, p) => s + (p.promised_amount || 0), 0);
  return (
    <div className="card">
      <div className="hd-inline">
        <div>
          <h2 style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span className={`g-pill g-${tone}`}>{label}</span>
            <span className="count">{items.length}</span>
          </h2>
          {items.length > 0 && (
            <div className="muted small">{title} · {money(sums)} promised</div>
          )}
        </div>
      </div>
      {items.length === 0 ? (
        <div className="muted small" style={{ padding: "6px 0" }}>
          Nothing here — {title.toLowerCase()}.
        </div>
      ) : (
        items
          .slice()
          .sort((a, b) => (a.promised_date || "").localeCompare(b.promised_date || ""))
          .map((p) => {
            const a = actionFor(p.customer_name);
            return (
              <div key={p.signal_id + p.customer_name} className="promise-item">
                {chipFor(p)}
                <div className="p-info">
                  <span className="p-name">
                    {p.customer_name}
                    {a && <span className="badge b-pri-high" style={{ marginLeft: 8 }}>{a.priority}</span>}
                  </span>
                  <span className="p-sub muted">
                    {p.related_invoice ? `on ${p.related_invoice}` : "no invoice attached"}
                    {a ? ` · ${a.action_label}` : " · no specific action queued"}
                  </span>
                </div>
                <b className="p-date">{money(p.promised_amount)}</b>
                <span className={`badge ${p.status === "overdue" ? "b-state-overdue" : p.status === "due_today" ? "b-state-due_today" : "b-state-upcoming"}`}>
                  {dueText(p)}
                </span>
                {a?.draft_type && a.draft_type !== "none" && (
                  <button className="btn small ghost b-pri-tint" onClick={() => onReview(a)}>
                    Review email
                  </button>
                )}
                <button className="btn small ghost" onClick={() => onShowEmail({ subject: p.summary, body: p.summary })}>
                  <Eye size={13} /> Why
                </button>
              </div>
            );
          })
      )}
    </div>
  );
}