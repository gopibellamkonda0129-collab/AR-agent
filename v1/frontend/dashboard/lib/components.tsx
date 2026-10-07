"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  approveSendFollowUp,
  cancelChase,
  copyFollowUp,
  discardFollowUp,
  fetchAccounts,
  fetchInvoiceActionPanel,
  gmailAuthUrl,
  connectInbox,
  getFollowUp,
  pauseCustomer,
  resumeCustomer,
  saveFollowUp,
  setCustomerOwner,
  setNextAction,
  snoozeCustomer,
  TYPE_LABEL,
  type ActionItem,
  type ArProcessDoc,
  type ChaseStrategy,
  type CollectionsIntel,
  type CustomerArProcess,
  type FollowUp,
  type InvoiceActionPanel,
  type PaymentBehavior,
  type WhyLate,
} from "./api";
import {
  AlertTriangle,
  BarChart,
  CalendarClock,
  Check,
  CheckCircle,
  Clock,
  Copy,
  Info,
  Pen,
  Quote,
  Send,
  ShieldCheck,
  Sparkles,
  Target,
  TrendUp,
  X,
  XCircle,
} from "./icons";

/* ------------------------------ format utils ------------------------------ */

export const money = (n: number | null | undefined) =>
  n == null ? "—" : `$${n.toLocaleString(undefined, { minimumFractionDigits: 2 })}`;

export const num = (n: number | null | undefined) =>
  n == null ? "—" : n.toLocaleString();

export const timeAgo = (iso: string | null) => {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const s = Math.floor((Date.now() - d.getTime()) / 1000);
  if (s < 10) return "just now";
  if (s < 90) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
};

export const initials = (name: string) =>
  name.trim().split(/\s+/).slice(0, 2).map((p) => p[0]?.toUpperCase() || "").join("") || "?";

export const todayStr = () => {
  const d = new Date();
  const p = (x: number) => String(x).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
};

export const inNDays = (n: number) => {
  const d = new Date();
  d.setDate(d.getDate() + n);
  const p = (x: number) => String(x).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
};

export const fmtDate = (iso: string | null) => {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
};

/* ----------------------------- animated number ----------------------------- */

export function AnimatedNumber({
  value,
  className,
  format = (x: number) => x.toLocaleString(),
  duration = 700,
}: {
  value: number;
  className?: string;
  format?: (x: number) => string;
  duration?: number;
}) {
  const [disp, setDisp] = useState(() => (Number.isFinite(value) ? value : 0));
  const fromRef = useRef(0);
  const rafRef = useRef(0);

  useEffect(() => {
    const to = Number.isFinite(value) ? value : 0;
    const from = Number.isFinite(disp) ? disp : 0;
    fromRef.current = from;
    const t0 = performance.now();
    const step = (t: number) => {
      const p = Math.min(1, (t - t0) / duration);
      const e = 1 - Math.pow(1 - p, 3);
      setDisp(from + (to - from) * e);
      if (p < 1) rafRef.current = requestAnimationFrame(step);
    };
    rafRef.current = requestAnimationFrame(step);
    return () => cancelAnimationFrame(rafRef.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  return <span className={className}>{format(disp)}</span>;
}

/* --------------------------------- hooks --------------------------------- */

export function usePolling<T>(loader: () => Promise<T>, delayMs = 15000) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [tick, setTick] = useState(0);
  const loaderRef = useRef(loader);
  loaderRef.current = loader;

  const reload = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    let alive = true;
    const run = () =>
      loaderRef
        .current()
        .then((d) => alive && (setData(d), setError("")))
        .catch((e) => alive && setError(String(e)))
        .finally(() => alive && setLoading(false));
    run();
    const t = setInterval(run, delayMs);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [delayMs, tick]);

  return { data, loading, error, reload };
}

/* ----------------------------------- UI ----------------------------------- */

export function PageTitle({ title, sub, right, eyebrow }: { title: string; sub?: string; right?: React.ReactNode; eyebrow?: string }) {
  return (
    <div className="page-head">
      <div>
        {eyebrow && <div className="page-eyebrow">{eyebrow}</div>}
        <h1>{title}</h1>
        {sub && <p>{sub}</p>}
      </div>
      {right && <div className="page-head-right">{right}</div>}
    </div>
  );
}

export function Kpi({
  label,
  value,
  sub,
  tone,
  hint,
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: string;
  hint?: string;
}) {
  return (
    <div className={`kpi ${tone || ""}`}>
      <div className="k-label">
        {label}
        {hint && (
          <span className="hint" tabIndex={0}>
            <Info size={13} />
            <span className="hint-box">{hint}</span>
          </span>
        )}
      </div>
      <div className="k-num">{value}</div>
      {sub && <div className="k-sub">{sub}</div>}
    </div>
  );
}

export function Spinner() {
  return <div className="spinner" />;
}

export function EmptyState({ children }: { children: React.ReactNode }) {
  return <div className="empty-hint">{children}</div>;
}

export function Skeleton({ lines = 3, h, w, br }: { lines?: number; h?: number; w?: string | number; br?: number }) {
  return (
    <div className="grid" style={{ gap: 10 }}>
      {Array.from({ length: lines }).map((_, i) => (
        <div
          key={i}
          className="skel"
          style={i === 0 && lines > 1 && !h ? { height: 18 } : { height: h || 64, width: w, borderRadius: br }}
        />
      ))}
    </div>
  );
}

export function Modal({
  title,
  onClose,
  children,
  wide,
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
  wide?: boolean;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return createPortal(
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal${wide ? " wide" : ""}`}>
        <div className="modal-head">
          <h3>{title}</h3>
          <button className="x" onClick={onClose} aria-label="close">
            <X size={18} />
          </button>
        </div>
        <div className="modal-body">{children}</div>
      </div>
    </div>,
    document.body
  );
}

export function PriorityChip({ priority, score }: { priority: string; score?: number }) {
  return (
    <span className={`prio prio-${priority}`}>
      {priority.toUpperCase()}
      {score != null && <em>{score}</em>}
    </span>
  );
}

export function StatusPill({ status, dueDate }: { status: string; dueDate?: string | null }) {
  let cls = "due";
  let label = status || "due";
  const lower = (status || "").toLowerCase();
  if (lower === "paid") {
    cls = "paid";
    label = "Paid";
  } else if (lower === "overdue" || lower.includes("past")) {
    cls = "overdue";
    label = "Overdue";
  } else if (dueDate) {
    const diff = Math.ceil((new Date(dueDate).getTime() - Date.now()) / 86400000);
    if (diff <= 7) {
      cls = "due-soon";
      label = "Due soon";
    } else {
      cls = "due";
      label = "Due";
    }
  }
  return <span className={`s-pill ${cls}`}>{label}</span>;
}

export function FilterChips({
  items,
}: {
  items: { key: string; label: string; count: number; active: boolean; onClick: () => void; tone?: string }[];
}) {
  return (
    <div className="filter-chips" role="group">
      {items.map((f) => (
        <button
          key={f.key}
          className={`f-chip${f.active ? " active" : ""}`}
          onClick={f.onClick}
          style={f.tone ? ({ "--fc": f.tone } as React.CSSProperties) : undefined}
        >
          {f.tone && <span className="fc-dot" />}
          {f.label}
          {f.count > 0 && <b>{f.count}</b>}
        </button>
      ))}
    </div>
  );
}

/* --------------------------- follow-up composer --------------------------- */

export function FollowUpComposer({
  item,
  onClose,
  onChanged,
}: {
  item: ActionItem;
  onClose: () => void;
  onChanged?: () => void;
}) {
  const [fu, setFu] = useState<FollowUp | null>(null);
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [editMode, setEditMode] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const [sent, setSent] = useState(false);

  useEffect(() => {
    getFollowUp(item.customer_name)
      .then((d) => {
        setFu(d);
        setSubject(d.subject);
        setBody(d.body);
      })
      .catch((e) => setMsg({ kind: "err", text: String(e) }));
  }, [item.customer_name]);

  const go = async (fn: () => Promise<unknown>, okText: string) => {
    setBusy(true);
    setMsg(null);
    try {
      await fn();
      setMsg({ kind: "ok", text: okText });
      onChanged?.();
    } catch (e) {
      setMsg({ kind: "err", text: String(e) });
    } finally {
      setBusy(false);
    }
  };

  const noEmail = !fu || fu.draft_type === "none";

  const srcEmail = fu?.context?.latest_signal?.source_email;

  return (
    <Modal title={`Follow-up • ${item.customer_name}`} onClose={onClose} wide>
      <div className="composer-context">
        <div className="fu-kicker">
          <Sparkles size={15} /> AI Follow-up
        </div>
        <div className="fu-reason">
          {item.overdue_amount > 0 ? `${money(item.overdue_amount)} overdue` : `${money(item.total_outstanding)} outstanding`}
          {item.max_days_overdue > 0 && <> · {item.max_days_overdue}d past due</>}
          {item.primary_invoice_number && <> · {item.primary_invoice_number}</>}
        </div>
        <div className="fu-src">
          {item.action_label} · recommendation confidence{" "}
          <span className="rec-conf">{Math.round(item.recommendation_confidence * 100)}%</span>
        </div>
      </div>

      {srcEmail && (
        <div className="card" style={{ marginBottom: 14, padding: 12 }}>
          <div className="fu-kicker" style={{ marginBottom: 5 }}>
            <Quote size={13} /> Why contact them — the customer&apos;s own email
          </div>
          <div className="ev-meta">
            {srcEmail.subject || "(no subject)"} · from{" "}
            {srcEmail.from_name || srcEmail.from_email}
            {srcEmail.received_at ? <> · {fmtDate(srcEmail.received_at)}</> : ""}
          </div>
          {fu?.context?.latest_signal?.source_email_body && (
            <div className="ev-quote" style={{ marginTop: 8 }}>
              {fu.context.latest_signal.source_email_body}
            </div>
          )}
        </div>
      )}

      {msg && <div className={`banner ${msg.kind === "err" ? "err" : ""}`}>{msg.text}</div>}

      {noEmail ? (
        <EmptyState>
          <b>No follow-up email needed for this action.</b>
          <span className="muted">{fu?.note}</span>
        </EmptyState>
      ) : (
        <div className="draft">
          {editMode ? (
            <>
              <label className="field">
                <span>Subject</span>
                <input value={subject} onChange={(e) => setSubject(e.target.value)} />
              </label>
              <label className="field">
                <span>Body</span>
                <textarea rows={12} value={body} onChange={(e) => setBody(e.target.value)} />
              </label>
            </>
          ) : (
            <div className="email-preview">
              <div className="ep-head">
                <span>
                  To: <b>{item.customer_email || item.customer_name}</b>
                </span>
                <span>
                  Subject: <b>{subject}</b>
                </span>
              </div>
              <div className="ep-body">{body}</div>
            </div>
          )}

          {fu?.status === "sent" && (
            <div className="banner" style={{ marginTop: 12 }}>
              This email was already sent with your approval.
            </div>
          )}

          <div className="composer-actions">
            <button
              className="btn violet"
              disabled={busy || sent}
              onClick={() =>
                go(async () => {
                  const d = await saveFollowUp(item.customer_name, {
                    draft_type: fu!.draft_type,
                    subject,
                    body,
                  });
                  setFu(d);
                  setSent(true);
                  setEditMode(false);
                  const r = await approveSendFollowUp(d.id);
                  if (!r.approved) throw new Error(r.message);
                  if (!r.sent) {
                    setMsg({ kind: "ok", text: "Approval recorded. " + r.message });
                  } else {
                    setMsg({ kind: "ok", text: `Sent to ${item.customer_email}.` });
                  }
                }, "Saving…")
              }
            >
              <Send size={15} /> Approve &amp; Send
            </button>
            <button className="btn ghost" disabled={busy} onClick={() => setEditMode((m) => !m)}>
              <Pen size={14} /> {editMode ? "Close editor" : "Edit"}
            </button>
            <button
              className="btn ghost"
              disabled={busy}
              onClick={() =>
                go(async () => {
                  const d = await saveFollowUp(item.customer_name, {
                    draft_type: fu!.draft_type,
                    subject,
                    body,
                  });
                  setFu(d);
                }, "Draft saved (not sent).")
              }
            >
              <CheckSaved size={14} /> Save edits
            </button>
            <button
              className="btn ghost"
              disabled={busy}
              onClick={async () => {
                await go(async () => {
                  await copyFollowUp(fu!.id);
                  await navigator.clipboard?.writeText(`To: ${item.customer_email}\nSubject: ${subject}\n\n${body}`);
                }, "Copied to clipboard.");
              }}
            >
              <Copy size={14} /> Copy
            </button>
            <button
              className="btn ghost danger"
              disabled={busy}
              onClick={() => go(() => discardFollowUp(fu!.id), "Draft discarded. You can generate a fresh one.")}
            >
              Discard
            </button>
          </div>

          <p className="footnote">
            <ShieldCheck size={13} style={{ verticalAlign: -2, marginRight: 4, color: "var(--green)" }} />
            <b>Human approval required.</b> Nothing is sent from this product without an explicit click above.
            Dollar figures and quotes come from your ledger and the customer&apos;s own email — never invented.
          </p>
        </div>
      )}
    </Modal>
  );
}

function CheckSaved(props: { size?: number }) {
  return (
    <svg width={props.size} height={props.size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
      <path d="M20 6L9 17l-5-5" />
    </svg>
  );
}

/* -------------------------------- action card ------------------------------ */

function ReadinessChip({ r }: { r: NonNullable<ActionItem["readiness"]> }) {
  return (
    <span className={`rdn-chip tone-${r.tone}`} title={r.summary}>
      {r.label}
    </span>
  );
}

export function ActionItemView({
  item,
  onReview,
  onContacted,
  onSnooze,
  onReactivate,
  onSelect,
  onOwnerChanged,
  onControl,
}: {
  item: ActionItem;
  onReview: () => void;
  onContacted: () => void;
  onSnooze: () => void;
  onReactivate?: () => void;
  onSelect?: () => void;
  onOwnerChanged?: () => void;
  onControl?: () => void;
}) {
  const snoozed = item.status === "snoozed";
  const sig = item.latest_signal;
  const conf = Math.round(item.recommendation_confidence * 100);

  const handleClick = (e: React.MouseEvent) => {
    const t = e.target as HTMLElement;
    if (t.closest("button, a, summary, input, .ac-details")) return;
    onSelect?.();
  };

  return (
    <div className={`action-card${snoozed ? " snoozed" : ""}`} data-priority={item.priority} onClick={handleClick}>
      <div className="ac-meta-row">
        <PriorityChip priority={item.priority} score={item.priority_score} />
        <ExceptionBadge group={item.exception_group} label={item.exception_label} />
        <CategoryBadge category={item.action_category} />
        {item.chase && (
          <span className="st-mini" data-tone={item.chase.tone}>
            {item.chase.stage_label}
          </span>
        )}
        {item.readiness && <ReadinessChip r={item.readiness} />}
        {item.stuck?.current_stage && item.stuck.current_stage !== "No known blocker" && (
          <span className="st-mini stuck-mini" title={item.stuck.blocker || item.stuck.where || ""}>
            {item.stuck.current_stage}
          </span>
        )}
        {item.decision_order && (
          <span className="st-mini step" title={item.decision_order_label || ""}>
            {item.decision_order}
          </span>
        )}
        {item.next_action_override && (
          <span className="st-mini override-mini" title="Manual next-action override set by the team">
            manual action
          </span>
        )}
        <span className="ac-meta">
          {item.primary_invoice_number && <span>{item.primary_invoice_number}</span>}
          {item.max_days_overdue > 0 && <span>{item.max_days_overdue}d overdue</span>}
          {item.overdue_amount > 0 && <span>{money(item.overdue_amount)} overdue</span>}
          {(item.amount_x_days ?? 0) > 0 && (
            <span className="rdn-chip tone-amber" title="Amount overdue × days overdue — cash-at-risk indicator">
              cash at risk {money(item.amount_x_days ?? 1)}
            </span>
          )}
          {!snoozed && item.last_contacted_at && <span>contacted {timeAgo(item.last_contacted_at)}</span>}
        </span>
      </div>
      <ComparisonNote item={item} />

      <div className="ac-head">
        <b className="ac-name2">{item.customer_name}</b>
        <span className="ac-amt2">{money(item.total_outstanding)}</span>
      </div>

      {snoozed && item.snoozed_until && (
        <span className="muted small">snoozed until {item.snoozed_until}</span>
      )}

      <div className="ac-signal">
        <Quote size={15} />
        <span className="ac-detected-txt">
          {sig ? (
            <>
              <b>{TYPE_LABEL[sig.signal_type] || sig.signal_type}</b> — {sig.summary}
            </>
          ) : (
            "No open signal, but cash is still at risk."
          )}
        </span>
      </div>

      <div className="ai-surf ac-reco2">
        <span className="ai-badge">
          <Sparkles size={13} /> AI recommendation
        </span>
        <b className="ac-reco2-txt">{item.action_label}</b>
        <p className="ac-why2">{item.reason}</p>
        <div className="ac-conf2">
          <span className="conf" title={`Recommendation confidence ${conf}%`}>
            <div style={{ width: `${conf}%` }} />
          </span>
          <span className="muted small">confidence {conf}%</span>
          <span className="muted small">follow up by {item.suggested_follow_up_date || "soon"}</span>
        </div>
      </div>

      <div className="ac-actions">
        <button className="btn small" onClick={onReview}>
          <Sparkles size={13} /> Review AI follow-up
        </button>
        <button className="btn small ghost" onClick={onContacted}>
          Mark contacted
        </button>
        {snoozed ? (
          <button className="btn small ghost" onClick={onReactivate}>
            Reactivate
          </button>
        ) : (
          <button className="btn small ghost" onClick={onSnooze}>
            Snooze
          </button>
        )}
        {onControl && (
          <button className="btn small ghost" onClick={onControl} title="Pause chasing, cancel the chase, or override the recommended next action">
            Follow-up control
          </button>
        )}
      </div>
      <div className="ac-owner"><OwnerOverride item={item} onChanged={onOwnerChanged} /></div>

      <details className="ac-details">
        <summary>Evidence · reasoning · history</summary>
        <div style={{ display: "grid", gap: 10 }}>
          {sig?.source_email && (
            <div className="ac-evidence">
              <span className="ev-meta">
                {sig.source_email.subject || "(no subject)"} · from{" "}
                {sig.source_email.from_name || sig.source_email.from_email}
                {sig.source_email.received_at ? ` · ${fmtDate(sig.source_email.received_at)}` : ""}
              </span>
              {sig.source_email_body && <span className="ev-quote">{sig.source_email_body}</span>}
            </div>
          )}
          {item.priority_reasons.length > 0 && (
            <div className="ac-reasons">
              {item.priority_reasons.map((r, i) => (
                <span key={i} className="chip">
                  {r}
                </span>
              ))}
            </div>
          )}
          {item.why_late && (
            <div className="wl-mini">
              <span className="chip chip-violet">{item.why_late.label}</span>
              <span className="wl-mini-head">{item.why_late.headline}</span>
              <span className="wl-mini-rec muted">{item.why_late.recommended}</span>
            </div>
          )}
          {item.behavior && item.behavior.reliability_score != null && (
            <div className="beh-mini">
              reliability <b>{item.behavior.reliability_score}</b>
              {item.behavior.late_count != null && <> · pays late {item.behavior.late_count}/{item.behavior.total_payments}</>}
              {(item.behavior.avg_delay_days ?? 0) > 0 && <> · avg +{item.behavior.avg_delay_days}d late</>}
              {item.behavior.promises_count > 0 && <> · promises {item.behavior.promises_kept}/{item.behavior.promises_count} kept</>}
              {item.behavior.promises_kept_percent != null && <> · promise kept {item.behavior.promises_kept_percent}%</>}
              {item.behavior.partial_payments > 0 && <> · pays in instalments ({item.behavior.partial_payments}×)</>}
            </div>
          )}
          <PromiseBreakdownTable rows={item.behavior?.promise_breakdown} />
          {item.pre_due?.needed && item.pre_due.email_example && (
            <div className="pre-due-box">
              <b className="pre-due-title">
                Confirm payment readiness · invoice {item.pre_due.invoice_number} due in {item.pre_due.due_in_days}d
              </b>
              {item.pre_due.check_label && (
                <span className={`proc-chip pc-${item.pre_due.check_label === "BLOCKED" ? "blocked" : item.pre_due.check_label === "PARTIALLY UNKNOWN" ? "approval" : "paid"}`}>
                  {item.pre_due.check_label.toLowerCase()}
                </span>
              )}
              {item.pre_due.checklist?.length > 0 && (
                <ul className="pd-check">
                  {item.pre_due.checklist.map((c, i) => (
                    <li key={i} className={`pd-c-${c.state}`} title={`${c.kind} — ${c.note}`}>
                      <span className="pd-c-dot" />
                      {c.step}
                      <em>{c.state === "ok" ? c.kind.toLowerCase() : c.state.replace("_", " ")}</em>
                    </li>
                  ))}
                </ul>
              )}
              <pre className="pd-email">{item.pre_due.email_example}</pre>
            </div>
          )}
          {item.posture && <PosturePill posture={item.posture} />}
          {item.ownership && (
            <div className="own-row">
              <span><b>Owner</b> {item.ownership.who}</span>
              <span><b>When</b> {item.ownership.when || "—"}</span>
              <span className="own-why"><b>Why</b> {item.ownership.why}</span>
              {item.ownership.evidence && (
                <span className="own-ev"><b>Evidence</b> {item.ownership.evidence}</span>
              )}
            </div>
          )}
          {item.contact_note && (
            <p className="muted small" style={{ margin: 0 }}>
              Your note: {item.contact_note}
            </p>
          )}
          <div className="ac-inspect">
            <span>
              action <b>{item.action}</b>
            </span>
            <span>
              draft <b>{item.draft_type || "none"}</b>
            </span>
            {item.promise && (
              <span>
                promise{" "}
                <b>
                  {money(item.promise.promised_amount)} by {item.promise.promised_date || "?"}{" "}
                  {item.promise.days_late > 0 ? `(${item.promise.days_late}d late)` : item.promise.status}
                </b>
              </span>
            )}
          </div>
        </div>
      </details>
    </div>
  );
}

/* ---------------------------- process vocabulary UI ------------------------- */

export const EVIDENCE_LABEL: Record<string, string> = {
  KNOWN: "known",
  INFERRED: "inferred",
  UNKNOWN: "unknown",
  "NOT OBSERVED": "not observed",
};

export function CategoryBadge({ category }: { category?: { category?: string; label?: string } }) {
  if (!category?.category) return null;
  const cat = category.category;
  return (
    <span className={`cat-badge cat-${cat}`} title={`Action focused on the ${cat} side of the process`}>
      {(category.label || cat).toLowerCase()}
    </span>
  );
}

export function PosturePill({ posture }: { posture?: { label?: string; reason?: string; confidence?: number; evidence_status?: string } }) {
  if (!posture?.label) return null;
  const lower = (posture.label || "").toLowerCase();
  const tone = lower.startsWith("unable") ? "posture-unable"
    : lower.startsWith("commitment") ? "posture-commit"
    : lower.startsWith("blocked") ? "posture-blocked"
    : "posture-collectable";
  const conf = posture.confidence != null ? `${Math.round(posture.confidence * 100)}%` : "";
  const ev = (posture.evidence_status || "").toLowerCase();
  return (
    <span className={`posture-pill ${tone}`} title={posture.reason}>
      {posture.label}
      {conf && <em className="posture-conf">{conf}</em>}
      {ev && <i className={`posture-ev posture-ev-${ev}`} />}
    </span>
  );
}

export function ProcessStatusChip({ ps }: { ps?: { status?: string; status_label?: string; stage?: string; blocker?: string | null; evidence_status?: string; confidence?: number; evidence_items?: { source: string; summary: string; evidence_status: string; date: string | null }[] } }) {
  if (!ps?.status) return null;
  const st = ps.status;
  const tone =
    st === "paid" ? "paid"
    : st === "disputed" ? "disputed"
    : st === "payment_overdue" ? "overdue"
    : st === "approval_pending" ? "approval"
    : st === "po_pending" ? "po"
    : st === "process_blocked" ? "blocked"
    : st === "payment_promised" ? "promised"
    : st === "ready_for_payment" ? "ready"
    : st === "received" || st === "receipt_unknown" ? "receipt"
    : "sent";
  const ev = ps.evidence_status || "UNKNOWN";
  const conf = ps.confidence != null ? `${Math.round(ps.confidence * 100)}%` : "";
  const title = `${ps.status_label || ps.stage || st}${ps.blocker ? ` — ${ps.blocker}` : ""}${ps.stage ? ` · ${ps.stage}` : ""}`;
  return (
    <span className={`proc-chip pc-${tone}`} title={title}>
      <i className={`pc-dot ev-${ev.toLowerCase()}`} />
      {ps.status_label || ps.stage || st}
      {(ps.blocker || conf) && <em className="pc-sub">{conf}</em>}
    </span>
  );
}

/* ------------------------------ V1.3 additions ----------------------------- */

const EXCEPTION_TONE: Record<string, string> = {
  missed_promise: "ex-missed",
  dispute: "ex-dispute",
  blocked: "ex-blocked",
  verify: "ex-verify",
  pre_due: "ex-predue",
  no_response: "ex-norp",
  overdue: "ex-overdue",
  question: "ex-question",
  routine: "ex-routine",
};

export function ExceptionBadge({ group, label }: { group?: string; label?: string }) {
  if (!group) return null;
  return (
    <span className={`ex-badge ${EXCEPTION_TONE[group] || "ex-routine"}`} title={
      "What makes this account exceptional — grouped beyond the routine 'cash is overdue, chase it' list."
    }>
      {label || group}
    </span>
  );
}

export function ComparisonNote({ item }: { item: ActionItem }) {
  if (!item.comparison_reason && !item.simple_priority_rank) return null;
  const marker =
    item.simple_priority_rank && item.agent_rank
      ? item.agent_rank < item.simple_priority_rank
        ? "promoted"
        : item.agent_rank > item.simple_priority_rank
          ? "held"
          : "matches"
      : "";
  return (
    <div className="cmp-note" title="Agent priority vs a plain amount × days sort">
      <CalendarClock size={13} />
      <span>
        {item.simple_priority_rank ? <>amount × days rank #{item.simple_priority_rank}</> : "amount × days not computed"}
        {item.agent_rank ? <> · intelligence rank #{item.agent_rank}</> : null}
        {marker && <em className={`cmp-${marker}`}> · {marker}</em>}
      </span>
      {item.comparison_reason && <span className="cmp-why">{item.comparison_reason}</span>}
    </div>
  );
}

export function OwnerOverride({ item, onChanged }: { item: ActionItem; onChanged?: () => void }) {
  const [open, setOpen] = useState(false);
  const [owner, setOwner] = useState(item.ownership?.override_value || item.owner_override || "");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  const manual = !!item.ownership?.manual;
  const who = item.ownership?.who || "—";

  const save = async (clear?: boolean) => {
    setBusy(true);
    setMsg("");
    try {
      await setCustomerOwner(item.customer_name, clear ? "" : owner);
      setMsg(clear ? "Cleared — engine owner restored." : `Owner set to "${owner}".`);
      onChanged?.();
    } catch (e) {
      setMsg(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={`owner-ctrl${manual ? " manual" : ""}`}>
      <span className="owner-pill" title={item.ownership?.why || "engine-assigned owner"}>
        <Target size={13} />
        <b>{manual ? "Override" : "Owner"}</b> {who}
        {manual && <em className="own-manual-tag">manual</em>}
      </span>
      <button className="btn tiny ghost" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        {open ? "Close" : manual ? "Change" : "Assign"}
      </button>
      {open && (
        <div className="owner-pop">
          <div className="field" style={{ marginTop: 8 }}>
            <label htmlFor={`ow-${item.customer_name}`}>Assign a teammate (blank resets to engine)</label>
            <input
              id={`ow-${item.customer_name}`}
              value={owner}
              onChange={(e) => setOwner(e.target.value)}
              placeholder="e.g. AR Lead"
            />
          </div>
          <div className="row-btns" style={{ marginTop: 0 }}>
            <button className="btn small" disabled={busy || !owner.trim()} onClick={() => save(false)}>
              Save owner
            </button>
            {manual && (
              <button className="btn small ghost" disabled={busy} onClick={() => save(true)}>
                Reset to engine
              </button>
            )}
          </div>
          {msg && <div className={`banner ${msg.includes("set") ? "" : "err"}`}>{msg}</div>}
        </div>
      )}
    </div>
  );
}

function Circuit() {
  return null;
}

export function PromiseBreakdownTable({ rows }: { rows?: { outcome: string; promised_date: string | null; promised_amount: number | null; related_invoice: string; status_label: string; late_days: number | null; note: string }[] }) {
  if (!rows?.length) return null;
  return (
    <div className="pb-wrap">
      <div className="pb-head">Promise ledger — what they said, what happened</div>
      <div className="pb-list">
        {rows.map((p, i) => (
          <div key={i} className={`pb-row pb-${p.outcome}`}>
            <span className="pb-date">{fmtDate(p.promised_date)}</span>
            <span className="pb-inv">{p.related_invoice || "—"}</span>
            <span className="pb-amt">{money(p.promised_amount)}</span>
            <span className={`pb-status pb-${p.outcome}`}>{p.status_label || p.outcome}</span>
            {p.late_days != null && <em className="pb-late">+{p.late_days}d late</em>}
            {p.note && <span className="pb-note muted small">{p.note}</span>}
          </div>
        ))}
      </div>
    </div>
  );
}

export function EvidenceDrawer({ invoice, ps, onClose }: {
  invoice: { invoice_number: string; customer_name?: string };
  ps?: InvoiceEvidence | null;
  onClose: () => void;
}) {
  const items = ps?.evidence_items || [];
  return (
    <Modal title={`Evidence · ${invoice.invoice_number}`} onClose={onClose}>
      <p className="muted small" style={{ marginTop: 0 }}>
        {invoice.customer_name ? `${invoice.customer_name} · ` : ""}what the product actually knows (no invented facts).
      </p>
      {items.length === 0 ? (
        <EmptyState>
          <b>No structured evidence recorded for this invoice.</b>
          <span className="muted">Read the status chips and free-text evidence below.</span>
          <pre className="pd-email">{ps?.evidence?.join("\n") || "—"}</pre>
        </EmptyState>
      ) : (
        <div className="ev-drawer-list">
          {items.map((e, i) => (
            <div key={i} className={`ev-item ev-${(e.evidence_status || "unknown").toLowerCase()}`}>
              <span className="ev-src">{e.source}</span>
              <span className="ev-summary">{e.summary}</span>
              <span className="ev-row-meta">
                <span className={`pc-dot ev-${(e.evidence_status || "unknown").toLowerCase()}`} />
                {EVIDENCE_LABEL[e.evidence_status] || e.evidence_status}
                {e.date && <> · {fmtDate(e.date)}</>}
              </span>
            </div>
          ))}
        </div>
      )}
      {ps?.status_label && (
        <div className="muted small" style={{ marginTop: 12 }}>
          Status: <b>{ps.status_label}</b>
          {ps.stage ? ` · ${ps.stage}` : ""}
          {ps.blocker ? ` · blocked on ${ps.blocker}` : ""}
        </div>
      )}
    </Modal>
  );
}

type InvoiceEvidence = {
  status_label?: string;
  stage?: string;
  blocker?: string | null;
  evidence_status?: string;
  confidence?: number;
  evidence?: string[];
  evidence_items?: { source: string; summary: string; evidence_status: string; date: string | null }[];
};

export function StuckPanel({ stuck }: { stuck?: { current_stage?: string; blocker?: string | null; where?: string; evidence?: string | null; confidence?: number | string | null; next_action?: string } }) {
  if (!stuck) return null;
  const conf =
    stuck.confidence == null
      ? null
      : typeof stuck.confidence === "number"
        ? Math.round((stuck.confidence as number) * 100)
        : (({ high: 90, medium: 70, low: 50 } as Record<string, number>)[String(stuck.confidence).toLowerCase()] ?? null);
  return (
    <div className="panel intel-panel stuck-panel">
      <div className="panel-head">
        <span className="fu-kicker" style={{ margin: 0 }}>
          <Info size={14} /> Where is this invoice stuck?
        </span>
        {conf != null && <span className="muted small">confidence {conf}%</span>}
      </div>
      <div className="stuck-tags">
        <span className="chip chip-violet">{stuck.current_stage || "Unknown"}</span>
        {stuck.blocker && <span className="chip chip-amber">{stuck.blocker}</span>}
        {stuck.where && <span className="chip">{stuck.where}</span>}
      </div>
      {stuck.evidence && (
        <blockquote className="wl-evidence ev-quote">
          <Quote size={13} /> “{stuck.evidence}”
        </blockquote>
      )}
      {stuck.next_action && (
        <div className="ci-reco" style={{ marginTop: 8 }}>
          <Sparkles size={14} />
          <span>
            <b>Next step</b>
            <em>{stuck.next_action}</em>
          </span>
        </div>
      )}
    </div>
  );
}

export function CustomerProcessPanel({ ar }: { ar?: { typical?: CustomerArProcess["typical"]; requirements?: CustomerArProcess["requirements"]; current?: CustomerArProcess["current"]; posture?: CustomerArProcess["posture"] } }) {
  if (!ar) return null;
  const nextAction = ar.current?.next_action || "";
  return (
    <div className="panel intel-panel proc-panel">
      <div className="panel-head">
        <span className="fu-kicker" style={{ margin: 0 }}>
          <CalendarClock size={14} /> AR process — where they are
        </span>
        <PosturePill posture={ar.posture} />
      </div>
      {ar.current && (
        <div className="stuck-tags" style={{ marginBottom: 6 }}>
          <span className="chip chip-violet">{ar.current.current_stage || "Unknown"}</span>
          {ar.current.blocker && <span className="chip chip-amber">{ar.current.blocker}</span>}
        </div>
      )}
      {ar.requirements && (
        <div className="proc-reqs">
          {ar.requirements.known_invoice_issues?.length > 0 && (
            <span className="chip chip-amber">
              issues: {ar.requirements.known_invoice_issues.join(", ")}
            </span>
          )}
          {ar.requirements.approval_process === "known" && (
            <span className="chip chip-blue">customer approval required</span>
          )}
          {ar.requirements.po_required === "known" && (
            <span className="chip chip-blue">PO required</span>
          )}
          {ar.requirements.documentation === "known" && (
            <span className="chip chip-blue">docs requested</span>
          )}
          <span className="muted small">
            {ar.requirements.ap_contact && ar.requirements.ap_contact !== "unknown"
              ? `AP contact · ${ar.requirements.ap_contact}`
              : "AP contact unknown"}
          </span>
        </div>
      )}
      {ar.typical && (ar.typical.promises_kept_percent != null || ar.typical.avg_delay_days != null) && (
        <div className="beh-pcts" style={{ marginTop: 6 }}>
          {ar.typical.avg_delay_days != null && (
            <span className="chip">avg delay {ar.typical.avg_delay_days}d</span>
          )}
          {ar.typical.promises_kept_percent != null && (
            <span className={ar.typical.promises_kept_percent < 50 ? "chip chip-red" : "chip chip-blue"}>
              promise kept {ar.typical.promises_kept_percent}%
            </span>
          )}
        </div>
      )}
      {nextAction.length > 0 && (
        <div className="ci-reco" style={{ marginTop: 8 }}>
          <Sparkles size={14} />
          <span>
            <b>Next step</b>
            <em>{nextAction}</em>
          </span>
        </div>
      )}
    </div>
  );
}

export function ArProcessCard({ doc }: { doc?: { observed?: ArProcessDoc["observed"]; recommended?: ArProcessDoc["recommended"]; note?: string } }) {
  if (!doc) return null;
  return (
    <div className="ar-proc-card">
      <div className="grid grid-2">
        <div className="panel">
          <h3 className="panel-title" style={{ marginTop: 0 }}>Observed — from your ledger &amp; emails</h3>
          <div className="ar-steps">
            {doc.observed?.map((s) => (
              <div key={s.key} className={`ar-step st-${(s.state || "unknown").toLowerCase().replace(/[\s]+/g, "-")}`}>
                <span className="ar-step-no">{s.step}</span>
                <div className="ar-step-body">
                  <div className="ar-step-top">
                    <b>{s.label}</b>
                    <span className={`proc-chip pc-${s.state === "KNOWN" ? "paid" : s.state === "INFERRED" ? "sent" : "blocked"}`}>
                      {EVIDENCE_LABEL[s.state] || (s.state || "unknown").toLowerCase()}
                      {s.count != null ? ` · ${s.count}` : ""}
                    </span>
                  </div>
                  <span className="muted small">{s.note}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
        <div className="panel">
          <h3 className="panel-title" style={{ marginTop: 0 }}>Recommended — the process to hold</h3>
          <div className="ar-steps rec">
            {doc.recommended?.map((s) => (
              <div key={s.step} className="ar-step">
                <span className="ar-step-no">{s.step}</span>
                <div className="ar-step-body">
                  <b>{s.label}</b>
                  <span className="muted small">{s.detail}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
      <p className="footnote">{doc.note}</p>
    </div>
  );
}

/* --------------------------- collections intelligence panels ------------------ */

export function BehaviorBar({ score, hr }: { score: number | null; hr?: boolean }) {
  const v = score == null ? 0 : Math.max(0, Math.min(100, score));
  return (
    <div className={`beh-bar${hr ? " hr" : ""}`} aria-label={`reliability ${v}`}>
      <div className="beh-track">
        <div className={`beh-fill bf-${score == null ? "na" : v < 40 ? "low" : v < 60 ? "avg" : v < 80 ? "good" : "exc"}`} style={{ width: `${v}%` }} />
      </div>
      <span className="beh-val">{score == null ? "—" : v}</span>
    </div>
  );
}

export function BehaviorPanel({ behavior }: { behavior: PaymentBehavior }) {
  const stats: { label: string; value: string; tone?: string }[] = [
    { label: "On-time payments", value: behavior.on_time_count == null ? "—" : String(behavior.on_time_count) },
    { label: "Paid late", value: behavior.late_count == null ? "—" : String(behavior.late_count), tone: (behavior.late_count ?? 0) > 0 ? "red" : "" },
    { label: "Avg delay", value: behavior.avg_delay_days == null ? "—" : `${behavior.avg_delay_days}d`, tone: (behavior.avg_delay_days ?? 0) > 0 ? "amber" : "" },
    { label: "Promises kept", value: `${behavior.promises_kept}/${behavior.promises_count}`, tone: behavior.promises_missed > 0 ? "amber" : "" },
    { label: "Last payment", value: behavior.last_payment_date ? fmtDate(behavior.last_payment_date) : "—" },
    { label: "Current overdue", value: money(behavior.current_overdue), tone: behavior.current_overdue > 0 ? "red" : "" },
  ];
  return (
    <div className="panel intel-panel beh-panel">
      <div className="panel-head">
        <span className="fu-kicker" style={{ margin: 0 }}>
          <BarChart size={14} /> Payment behaviour
        </span>
        <span className={`beh-label bl-${behavior.reliability_score == null ? "na" : behavior.reliability_score >= 80 ? "exc" : behavior.reliability_score >= 60 ? "good" : behavior.reliability_score >= 40 ? "avg" : "low"}`}>
          {behavior.reliability_label}
        </span>
      </div>
      <div className="beh-score-row">
        <BehaviorBar score={behavior.reliability_score} />
        <span className="muted small">Payment reliability /100</span>
      </div>
      {(behavior.on_time_percent != null || behavior.promises_kept_percent != null || (behavior.partial_payments ?? 0) > 0) && (
        <div className="beh-pcts">
          {behavior.on_time_percent != null && (
            <span className="chip chip-green">{behavior.on_time_percent}% on-time</span>
          )}
          {behavior.promises_kept_percent != null && (
            <span className={behavior.promises_kept_percent < 50 ? "chip chip-red" : "chip chip-blue"}>
              promise kept {behavior.promises_kept_percent}%
            </span>
          )}
          {(behavior.partial_payments ?? 0) > 0 && (
            <span className="chip chip-amber">pays in instalments ({behavior.partial_payments}×)</span>
          )}
        </div>
      )}
      <div className="beh-grid">
        {stats.map((s) => (
          <div key={s.label} className="beh-stat">
            <b className={`${s.tone ? `t-${s.tone}` : ""}`}>{s.value}</b>
            <span>{s.label}</span>
          </div>
        ))}
      </div>
      {(behavior.late_payments?.length ?? 0) > 0 && (
        <div className="beh-late-list">
          {behavior.late_payments.map((l) => (
            <span key={l.invoice_number} className="beh-late-row">
              <Clock size={12} /> {l.invoice_number} · ${l.amount.toLocaleString()} · paid {l.delay_days}d after due ({fmtDate(l.paid_at)})
            </span>
          ))}
        </div>
      )}
      <div className="muted small" style={{ marginTop: 8 }}>
        The score is one view — the on-time %, promise-kept % and instalments above show the actual behaviour.
      </div>
    </div>
  );
}

export function CollectionsCard({
  c,
  readiness,
  pre_due,
}: {
  c: CollectionsIntel;
  readiness?: NonNullable<ActionItem["readiness"]>;
  pre_due?: NonNullable<ActionItem["pre_due"]>;
}) {
  const chips: { text: string; cls: string }[] = [];
  if (c.last_response_days != null) chips.push({ text: `last response ${c.last_response_days === 0 ? "today" : `${c.last_response_days}d ago`}`, cls: "chip-blue" });
  if (c.missed_promise?.promised_date) chips.push({ text: `previous promise missed · ${fmtDate(c.missed_promise.promised_date)}`, cls: "chip-red" });
  if (c.paid_late_count > 0) chips.push({ text: `paid late ${c.paid_late_count}×`, cls: "chip-amber" });
  if (!chips.length) chips.push({ text: "no payment history on file", cls: "" });

  return (
    <div className="panel intel-panel ci-panel">
      <div className="panel-head">
        <span className="fu-kicker" style={{ margin: 0 }}>
          <Clock size={14} /> Collections intelligence
        </span>
        <PriorityChip priority={c.risk} score={c.risk_score} />
      </div>
      <div className={`ci-hero${c.overdue_amount > 0 ? " hot" : ""}`}>
        <b className={c.overdue_amount > 0 ? "t-red" : ""}>{money(c.overdue_amount)}</b>
        <span className="ci-place">overdue{c.max_days_overdue > 0 ? ` · ${c.max_days_overdue}d` : ""}</span>
      </div>
      {readiness && (
        <div className="ci-rdn">
          <ReadinessChip r={readiness} />
          <span className="muted small">{readiness.summary}</span>
        </div>
      )}
      <div className="ci-chips">
        {chips.map((x, i) => (
          <span key={i} className={`chip ${x.cls}`}>{x.text}</span>
        ))}
      </div>
      {c.open_issue_types.length > 0 && (
        <div className="muted small" style={{ marginTop: 6 }}>
          open issue{c.open_issue_types.length > 1 ? "s" : ""}: {c.open_issue_types.join(", ")}
        </div>
      )}
      {c.risk_reasons.length > 0 && (
        <div className="ac-reasons" style={{ marginTop: 8 }}>
          {c.risk_reasons.slice(0, 3).map((r, i) => (
            <span key={i} className="chip">{r}</span>
          ))}
        </div>
      )}
      <div className="ci-reco">
        <Sparkles size={14} />
        <span>
          <b>{c.recommended_action}</b>
          <em>{c.recommended_reason}</em>
        </span>
      </div>
      {pre_due?.needed && (
        <div className="pre-due-box compact">
          <b className="pre-due-title">
            Confirm payment readiness · {pre_due.invoice_number} due in {pre_due.due_in_days}d
          </b>
          <pre className="pd-email">{pre_due.email_example}</pre>
        </div>
      )}
    </div>
  );
}

export function ChaseStrategyCard({ s }: { s: ChaseStrategy }) {
  return (
    <div className="panel intel-panel strat-card" data-tone={s.tone}>
      <div className="panel-head">
        <span className="fu-kicker" style={{ margin: 0 }}>
          <TrendUp size={14} /> Smart chase strategy
        </span>
        <span className="st-tone" data-tone={s.tone}>
          {s.tone}
        </span>
      </div>
      <div className="st-stage">
        <b>{s.stage_label}</b>
        <span className="muted small">what we&apos;ve sent before</span>
      </div>
      <p className="st-approach">{s.approach}</p>
      <div className="st-lists">
        <ul className="st-steps">
          {s.steps.map((x, i) => (
            <li key={i}>
              <Check size={13} /> {x}
            </li>
          ))}
        </ul>
        {s.avoid.length > 0 && (
          <ul className="st-avoid">
            {s.avoid.map((x, i) => (
              <li key={i}>
                <XCircle size={13} /> {x}
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="st-email">
        suggested draft <b>{s.email || "none (no email needed)"}</b>
        {s.flags.length > 0 && (
          <span className="st-flags">{s.flags.map((f) => `#${f}`).join("  ")}</span>
        )}
      </div>
    </div>
  );
}

export function WhyLateCard({ w }: { w: WhyLate }) {
  return (
    <div className="panel intel-panel why-card">
      <div className="panel-head">
        <span className="fu-kicker" style={{ margin: 0 }}>
          <AlertTriangle size={14} /> Why is this late?
        </span>
        <span className={`wl-cat wc-${(w.group || w.category).toLowerCase()}`}>{w.group_label || w.label}</span>
      </div>
      <p className="wl-head">{w.headline}</p>
      {w.evidence && (
        <blockquote className="wl-evidence ev-quote">
          <Quote size={13} /> “{w.evidence}”
          {w.evidence_date && <span className="wl-meta">{w.source_subject ? `${w.source_subject} · ` : ""}last mentioned {fmtDate(w.evidence_date)}</span>}
        </blockquote>
      )}
      <div className="wl-conf">
        {w.no_confirmed_payment_date ? (
          <span className="wl-flag bad">
            <XCircle size={13} /> No confirmed payment date
          </span>
        ) : (
          <span className="wl-flag ok">
            <CheckCircle size={13} /> Payment date on file
          </span>
        )}
      </div>
      <div className="ci-reco" style={{ marginTop: 10 }}>
        <Sparkles size={14} />
        <span>
          <b>Recommended</b>
          <em>{w.recommended}</em>
        </span>
      </div>
    </div>
  );
}

export function SnoozeModal({
  item,
  onClose,
  onSnoozed,
}: {
  item: ActionItem;
  onClose: () => void;
  onSnoozed: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const [custom, setCustom] = useState(todayStr());

  return (
    <Modal title={`Snooze • ${item.customer_name}`} onClose={onClose}>
      <p className="muted">Move this customer out of the queue and bring them back automatically later.</p>
      <div className="snooze-presets">
        {[
          { n: 3, label: "3 days" },
          { n: 7, label: "1 week" },
          { n: 14, label: "2 weeks" },
        ].map((p) => (
          <button
            key={p.n}
            className="btn ghost small"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              setMsg(null);
              try {
                await snoozeCustomer(item.customer_name, inNDays(p.n));
                setMsg({ kind: "ok", text: `Snoozed until ${inNDays(p.n)}.` });
                onSnoozed();
              } catch (e) {
                setMsg({ kind: "err", text: String(e) });
              } finally {
                setBusy(false);
              }
            }}
          >
            {p.label}
          </button>
        ))}
        <span className="muted small">or</span>
        <input className="note-input" type="date" value={custom} onChange={(e) => setCustom(e.target.value)} />
        <button
          className="btn ghost small"
          disabled={busy || !custom}
          onClick={async () => {
            setBusy(true);
            setMsg(null);
            try {
              await snoozeCustomer(item.customer_name, custom);
              setMsg({ kind: "ok", text: `Snoozed until ${custom}.` });
              onSnoozed();
            } catch (e) {
              setMsg({ kind: "err", text: String(e) });
            } finally {
              setBusy(false);
            }
          }}
        >
          Snooze to date
        </button>
      </div>
      {msg && <div className={`banner ${msg.kind === "err" ? "err" : ""}`}>{msg.text}</div>}
    </Modal>
  );
}

/* --------------------- [8][9][10] invoice lifecycle + action panel -------- */

export function LifecycleProgress({ lc, compact }: {
  lc?: { current_stage?: string; current_stage_label?: string; progress?: number; terminal?: string } | null;
  compact?: boolean;
}) {
  if (!lc) return null;
  const pct = Math.max(0, Math.min(100, Math.round(lc.progress ?? 0)));
  const done = (lc.terminal === "paid" && pct >= 100) || (lc.current_stage_label || "").toLowerCase() === "paid";
  const label = lc.current_stage_label || lc.current_stage || "—";
  return (
    <span
      className={`lc-wrap${done ? " lc-done" : ""}${compact ? " lc-compact" : ""}`}
      title={`Invoice lifecycle: ${label} — ${pct}% of the way to payment${lc.terminal ? ` · terminal: ${lc.terminal}` : ""}`}
    >
      {!compact && (
        <span className="lc-label">
          {label} <em>{pct}%</em>
        </span>
      )}
      <span className="lc-track">
        <i className="lc-fill" style={{ width: `${pct}%` }} />
      </span>
    </span>
  );
}

const RDY_TONE: Record<string, string> = {
  READY: "rdy-ready",
  CONFIRM: "rdy-confirm",
  "NOT READY": "rdy-notready",
  NOT_READY: "rdy-notready",
  UNKNOWN: "rdy-unknown",
};

export function ReadinessSummaryChip({ rs }: { rs?: { verdict?: string; verdict_label?: string; passed?: number; blockers?: string[] } | null }) {
  if (!rs?.verdict) return null;
  const tone = RDY_TONE[rs.verdict] || "rdy-unknown";
  return (
    <span
      className={`rdn-chip ${tone}`}
      title={rs.blockers?.length
        ? `Send readiness ${rs.verdict} — ${rs.passed ?? 0} checks passed, blocked on: ${rs.blockers.join(", ")}`
        : `Send readiness ${rs.verdict} — ${rs.passed ?? 0} checks passed`}
    >
      {rs.verdict_label || rs.verdict}
    </span>
  );
}

function LifeStagePill({ stage }: { stage: { state?: string; label?: string; evidence_status?: string; blocker?: string; note?: string } }) {
  return (
    <span
      className={`ls-pill ls-${stage.state || "upcoming"}`}
      title={`${stage.label || ""}${stage.evidence_status ? ` · ${stage.evidence_status.toLowerCase()}` : ""}${stage.blocker ? ` · blocked on ${stage.blocker}` : ""}${stage.note ? ` — ${stage.note}` : ""}`}
    >
      <i className={`pc-dot ev-${(stage.evidence_status || "UNKNOWN").toLowerCase()}`} />
      {stage.label}
      {stage.blocker && <em className="ls-block">blocked</em>}
    </span>
  );
}

export function InvoiceActionPanelModal({ invoiceId, invoiceLabel, onClose }: {
  invoiceId: string;
  invoiceLabel: string;
  onClose: () => void;
}) {
  const [panel, setPanel] = useState<InvoiceActionPanel | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    let live = true;
    fetchInvoiceActionPanel(invoiceId)
      .then((d) => live && setPanel(d))
      .catch((e) => live && setErr(String(e)));
    return () => { live = false; };
  }, [invoiceId]);

  return (
    <Modal title={`Action panel · ${invoiceLabel}`} onClose={onClose} wide>
      {err ? (
        <div className="banner err">{err}</div>
      ) : !panel ? (
        <div className="sk-pad"><Spinner /></div>
      ) : (
        <div className="ap-body">
          <div className="ap-hero">
            <div className="ap-amt">
              <b className="t-amber">{money(panel.amount_outstanding)}</b>
              <span className="muted small">{panel.customer_name}{panel.due_date ? ` · due ${fmtDate(panel.due_date)}` : ""}</span>
            </div>
            <div className="ap-hero-chips">
              <ProcessStatusChip ps={panel.process_status} />
              {panel.recommended_action.priority && (
                <PriorityChip priority={panel.recommended_action.priority} />
              )}
            </div>
          </div>

          <div className="ap-section">
            <div className="ap-sec-head">
              <span className="fu-kicker" style={{ margin: 0 }}><Target size={13} /> Lifecycle</span>
              <LifecycleProgress lc={panel.lifecycle} compact />
            </div>
            <div className="ls-strip">
              {panel.lifecycle.stages?.map((s) => (
                <LifeStagePill key={s.key} stage={s} />
              ))}
            </div>
          </div>

          <div className="ap-section">
            <div className="ap-sec-head">
              <span className="fu-kicker" style={{ margin: 0 }}><ShieldCheck size={13} /> Send readiness</span>
              <ReadinessSummaryChip rs={{ verdict: panel.readiness.verdict, verdict_label: panel.readiness.verdict_label, passed: panel.readiness.passed, blockers: panel.readiness.blockers }} />
            </div>
            <div className="rdy-tally">
              <span className="chip chip-green">{panel.readiness.passed} pass</span>
              <span className="chip chip-blue">{panel.readiness.warning} warning</span>
              <span className="chip chip-amber">{panel.readiness.unknown} unknown</span>
              {panel.readiness.blocked > 0 && <span className="chip chip-red">{panel.readiness.blocked} blocked</span>}
            </div>
            <div className="ap-checks">
              {panel.readiness.checks.map((c) => (
                <div key={c.key} className={`ap-check pc-${(c.status || "UNKNOWN").toLowerCase()}`}>
                  <i className={`pc-dot ev-${c.evidence.toLowerCase()}`} />
                  <b>{c.label}</b>
                  <span className={`chk-st s-${(c.status || "UNKNOWN").toLowerCase()}`}>{c.status}</span>
                  <em>{c.verify || c.note}</em>
                </div>
              ))}
            </div>
            {panel.readiness.verify_before_send.length > 0 && (
              <div className="ap-note">
                <Info size={13} /> verify before sending: {panel.readiness.verify_before_send.join(" · ")}
              </div>
            )}
          </div>

          <div className="ap-section">
            <div className="ap-sec-head">
              <span className="fu-kicker" style={{ margin: 0 }}><AlertTriangle size={13} /> Reminder safety switch</span>
              <span className={`vs-pill vs-${panel.reminder_safety.verdict.toLowerCase()}`}>
                {panel.reminder_safety.verdict_label || panel.reminder_safety.verdict}
              </span>
            </div>
            {panel.reminder_safety.product_rule && (
              <div className="ap-note">
                <ShieldCheck size={13} /> safety rule: this customer is blocked by {panel.recommended_action.exception_label || "a process issue"} — a generic payment demand would be counterproductive.
              </div>
            )}
            <p className="muted small" style={{ margin: "6px 0 8px" }}>{panel.reminder_safety.note}</p>
            <div className="ap-checks">
              {panel.reminder_safety.checks.map((c) => (
                <div key={c.key} className={`ap-check ${c.outcome ? "pc-green" : "pc-red"}`}>
                  <i className={`pc-dot ${c.outcome ? "ev-known" : "ev-inferred"}`} />
                  <b>{c.label}</b>
                  <span className={`chk-st ${c.outcome ? "s-pass" : "s-blocked"}`}>{c.outcome ? "clear" : "blocked"}</span>
                  <em>{c.note}</em>
                </div>
              ))}
            </div>
            {panel.reminder_safety.recommended_action && (
              <div className="ci-reco" style={{ marginTop: 8 }}>
                <Sparkles size={14} />
                <span><b>Recommended</b><em>{panel.reminder_safety.recommended_action}</em></span>
              </div>
            )}
          </div>

          <div className="ap-section">
            <div className="ap-sec-head">
              <span className="fu-kicker" style={{ margin: 0 }}><BarChart size={13} /> Payment readiness score</span>
              <span className={`pay-score pay-${panel.payment_readiness_score.tone}`}>
                <b>{panel.payment_readiness_score.score}</b>
                <span>{panel.payment_readiness_score.label}</span>
              </span>
            </div>
            <p className="muted small" style={{ margin: "6px 0 8px" }}>{panel.payment_readiness_score.method}</p>
            <div className="sig-list">
              {panel.payment_readiness_score.signals.map((s) => (
                <div key={s.key} className="sig-row">
                  <div className="sig-top">
                    <b>{s.label}</b>
                    <span className="muted small">{s.value}</span>
                    <span className="sig-w">{s.score}/{s.weight}</span>
                  </div>
                  <span className="sig-track">
                    <i
                      className={`sig-fill sig-${panel.payment_readiness_score.tone}`}
                      style={{ width: `${s.weight > 0 ? (s.score / s.weight) * 100 : 0}%` }}
                    />
                  </span>
                  <span className="muted small sig-reason">{s.reason}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="ap-section">
            <div className="ap-sec-head">
              <span className="fu-kicker" style={{ margin: 0 }}><Sparkles size={13} /> Recommended next step</span>
              <PriorityChip priority={panel.recommended_action.priority} />
            </div>
            <div className="ap-reco">
              <b>{panel.recommended_action.action_label}</b>
              <p className="muted small" style={{ margin: "4px 0 0" }}>{panel.recommended_action.reason}</p>
              <div className="pills" style={{ marginTop: 8 }}>
                <span className="chip chip-violet">{panel.recommended_action.exception_label}</span>
                {panel.recommended_action.chase_stage && <span className="chip">{panel.recommended_action.chase_stage}</span>}
                {panel.recommended_action.owner && <span className="chip chip-blue">owner · {panel.recommended_action.owner}</span>}
                {panel.recommended_action.suggested_follow_up && (
                  <span className="chip chip-amber">follow up by {fmtDate(panel.recommended_action.suggested_follow_up)}</span>
                )}
              </div>
            </div>
            <div className="ap-control">
              <span className="fu-kicker" style={{ margin: 0 }}><Clock size={13} /> Control state</span>
              <div className="pills" style={{ marginTop: 6 }}>
                {panel.control.paused ? (
                  <span className="chip chip-red">
                    paused {panel.control.paused_until ? `until ${fmtDate(panel.control.paused_until)}` : "indefinitely"}
                    {panel.control.paused_reason ? ` — ${panel.control.paused_reason}` : ""}
                  </span>
                ) : (
                  <span className="chip chip-green">active in queue</span>
                )}
                {panel.control.next_action_override && (
                  <span className="chip chip-blue">manual override · {panel.control.next_action_override}</span>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </Modal>
  );
}

/* --------------------- follow-up control center (pause / cancel / override) */

const OVERRIDE_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "— Auto (clear manual override) —" },
  { value: "MONITOR_PROMISE", label: "Monitor promise — no email yet" },
  { value: "FOLLOW_UP_IF_UNPAID", label: "Follow up today if not received" },
  { value: "FOLLOW_UP_MISSED_PROMISE", label: "Follow up on missed payment promise" },
  { value: "FOLLOW_UP", label: "Send follow-up" },
  { value: "INVESTIGATE_DISPUTE", label: "Investigate dispute" },
  { value: "REQUEST_CORRECTED_PO", label: "Request corrected PO" },
  { value: "REQUEST_APPROVAL_STATUS", label: "Check approval status" },
  { value: "RESEND_INVOICE", label: "Resend invoice" },
  { value: "PROVIDE_DOCUMENTS", label: "Provide requested documents" },
  { value: "FIND_ALTERNATE_CONTACT", label: "Find alternate contact (bounce)" },
  { value: "VERIFY_PAYMENT", label: "Verify payment / reconcile" },
  { value: "REPLY_TO_QUESTION", label: "Reply to customer question" },
  { value: "CONFIRM_PAYMENT_READINESS", label: "Confirm payment readiness" },
  { value: "ESCALATE", label: "Escalate follow-up" },
];

export function ControlCenterModal({ item, onClose, onChanged }: {
  item: ActionItem;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const [until, setUntil] = useState("");
  const [reason, setReason] = useState(item.paused_reason || "");
  const [cancelReason, setCancelReason] = useState("");
  const [overrideAction, setOverrideAction] = useState(item.next_action_override || "");

  const go = async (fn: () => Promise<unknown>, okText: string) => {
    setBusy(true);
    setMsg(null);
    try {
      await fn();
      setMsg({ kind: "ok", text: okText });
      onChanged();
    } catch (e) {
      setMsg({ kind: "err", text: String(e) });
    } finally {
      setBusy(false);
    }
  };

  const presets = [
    { n: 3, label: "3 days" },
    { n: 7, label: "1 week" },
    { n: 14, label: "2 weeks" },
  ];

  return (
    <Modal title={`Follow-up control · ${item.customer_name}`} onClose={onClose} wide>
      {msg && <div className={`banner ${msg.kind === "err" ? "err" : ""}`} style={{ marginBottom: 10 }}>{msg.text}</div>}

      <div className="ap-control">
        <span className="fu-kicker" style={{ margin: 0 }}><Clock size={13} /> Current state</span>
        <div className="pills" style={{ marginTop: 6 }}>
          {item.paused ? (
            <span className="chip chip-red">
              paused {item.paused_until ? `until ${fmtDate(item.paused_until)}` : "indefinitely"}
              {item.paused_reason ? ` — ${item.paused_reason}` : ""}
            </span>
          ) : (
            <span className="chip chip-green">active in queue</span>
          )}
          {item.next_action_override && <span className="chip chip-blue">manual override · {item.next_action_override}</span>}
        </div>
        {item.paused && (
          <div className="row-btns" style={{ marginTop: 8 }}>
            <button className="btn small" disabled={busy} onClick={() => go(() => resumeCustomer(item.customer_name), "Chase resumed — back in the queue.")}>
              Resume chasing
            </button>
          </div>
        )}
      </div>

      <div className="ap-grid-2">
        <div className="ap-control">
          <span className="fu-kicker" style={{ margin: 0 }}><CalendarClock size={13} /> Pause chasing</span>
          <p className="muted small" style={{ margin: "4px 0 8px" }}>
            Remove from the queue and bring it back automatically later, or hold indefinitely.
          </p>
          <div className="snooze-presets">
            {presets.map((p) => (
              <button
                key={p.n}
                className="btn ghost small"
                disabled={busy}
                onClick={() => go(() => pauseCustomer(item.customer_name, { until: inNDays(p.n), reason }), `Paused until ${inNDays(p.n)}.`)}
              >
                {p.label}
              </button>
            ))}
            <input className="note-input" type="date" value={until} onChange={(e) => setUntil(e.target.value)} title="Pause until a specific date" />
            <button
              className="btn ghost small"
              disabled={busy || !until}
              onClick={() => go(() => pauseCustomer(item.customer_name, { until, reason }), `Paused until ${until}.`)}
            >
              Pause to date
            </button>
          </div>
          <input
            className="note-input"
            style={{ marginTop: 8 }}
            placeholder="Reason (optional) — e.g. awaiting their AP cycle, owner away"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
          <div className="row-btns" style={{ marginTop: 8 }}>
            <button
              className="btn small ghost"
              disabled={busy}
              onClick={() => go(() => pauseCustomer(item.customer_name, { until: "", reason }), "Chasing paused indefinitely.")}
            >
              Pause indefinitely
            </button>
          </div>
        </div>

        <div className="ap-control">
          <span className="fu-kicker" style={{ margin: 0 }}><XCircle size={13} /> Cancel the scheduled chase</span>
          <p className="muted small" style={{ margin: "4px 0 8px" }}>
            Stop the automated chase for this account entirely. Recorded in the timeline as a team decision.
          </p>
          <input
            className="note-input"
            placeholder="Why? (optional) — e.g. paid offline, legal hold"
            value={cancelReason}
            onChange={(e) => setCancelReason(e.target.value)}
          />
          <div className="row-btns" style={{ marginTop: 8 }}>
            <button
              className="btn small danger"
              disabled={busy}
              onClick={() => go(() => cancelChase(item.customer_name, cancelReason), "Chase cancelled.")}
            >
              Cancel chase
            </button>
          </div>
        </div>
      </div>

      <div className="ap-control">
        <span className="fu-kicker" style={{ margin: 0 }}><Pen size={13} /> Override next action</span>
        <p className="muted small" style={{ margin: "4px 0 8px" }}>
          The AI keeps its recommendation; your manual choice wins and is shown as a team decision.
        </p>
        <div className="row-btns" style={{ marginTop: 0 }}>
          <select
            className="note-input"
            style={{ flex: 1, minWidth: 220 }}
            value={overrideAction}
            onChange={(e) => setOverrideAction(e.target.value)}
          >
            {OVERRIDE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
          <button
            className="btn small"
            disabled={busy || overrideAction === item.next_action_override}
            onClick={() => go(() => setNextAction(item.customer_name, overrideAction), overrideAction ? `Next action overridden to: ${overrideAction}.` : "Override cleared — AI recommendation restored.")}
          >
            Save override
          </button>
        </div>
      </div>
    </Modal>
  );
}

/* ------------------------------- connect inbox ----------------------------- */

export function ConnectPanel({ onConnected }: { onConnected?: () => void }) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  const onGmail = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setBusy(true);
    setMsg(null);
    const em = new FormData(e.currentTarget).get("email") as string;
    gmailAuthUrl(em)
      .then(async (d) => {
        window.open(d.auth_url, "_blank", "popup,width=520,height=620");
        setMsg({ kind: "ok", text: "Finish Google sign-in in the popup. This page updates automatically." });
        await new Promise((r) => setTimeout(r, 500));
      })
      .catch((err) => setMsg({ kind: "err", text: String(err) }))
      .finally(() => setBusy(false));
  };

  const onImap = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    setBusy(true);
    setMsg(null);
    const provider = String(f.get("provider") || "imap");
    const email = String(f.get("email") || "");
    const password = String(f.get("password") || "");
    const host = String(f.get("host") || (provider === "outlook" ? "outlook.office365.com" : "imap.gmail.com"));
    connectInbox({
      provider,
      email,
      display_name: email.split("@")[0],
      config: { email, password, host, port: "993" },
    })
      .then(() => {
        setMsg({ kind: "ok", text: `Connected ${email}. Sync the inbox to analyze customer mail.` });
        onConnected?.();
      })
      .catch((err) => setMsg({ kind: "err", text: String(err) }))
      .finally(() => setBusy(false));
  };

  return (
    <div className="connect-panel">
      <div className="connect-card">
        <h3>Gmail</h3>
        <p>Read-only authorization. AR finds who owes you, why they&apos;re late, and what to do.</p>
        {msg?.kind === "ok" && <div className="banner">{msg.text}</div>}
        {msg?.kind === "err" && <div className="banner err">{msg.text}</div>}
        <form onSubmit={onGmail}>
          <div className="field">
            <label htmlFor="gmail-email">Company mailbox (optional)</label>
            <input id="gmail-email" name="email" type="email" placeholder="ar@yourcompany.com" />
          </div>
          <button className="btn" disabled={busy}>
            Authorize Gmail
          </button>
        </form>
      </div>

      <div className="connect-card">
        <h3>Other mailboxes (IMAP)</h3>
        <p>Gmail app passwords or Outlook work here. Use the mailbox address, not a personal login.</p>
        {msg?.kind === "ok" && <div className="banner">{msg.text}</div>}
        {msg?.kind === "err" && <div className="banner err">{msg.text}</div>}
        <form onSubmit={onImap}>
          <div className="field">
            <label>Provider</label>
            <select name="provider" defaultValue="imap">
              <option value="imap">IMAP (Gmail / any server)</option>
              <option value="outlook">Outlook / Office 365</option>
            </select>
          </div>
          <div className="field">
            <label htmlFor="imap-email">Email / username</label>
            <input id="imap-email" name="email" type="email" required placeholder="ar@yourcompany.com" />
          </div>
          <div className="field">
            <label htmlFor="imap-pw">App password</label>
            <input id="imap-pw" name="password" type="password" required placeholder="••••••••" />
          </div>
          <div className="field">
            <label htmlFor="imap-host">IMAP host (optional)</label>
            <input id="imap-host" name="host" type="text" placeholder="imap.gmail.com" />
          </div>
          <button className="btn ghost" disabled={busy}>
            Connect
          </button>
        </form>
      </div>
    </div>
  );
}

export function useAccounts() {
  const { data } = usePolling(fetchAccounts, 60000);
  return data || [];
}

export function SyncedInboxStatus({ accounts }: { accounts: ReturnType<typeof useAccounts> }) {
  if (!accounts.length) return null;
  const last = accounts[0];
  return (
    <span className="conn">
      <span className="dot" />
      {last.provider === "demo" ? "workspace data" : `${last.email}`}
      {last.last_sync_status === "ok" && <em className="muted small">· synced {timeAgo(last.last_sync_at)}</em>}
    </span>
  );
}

export function CalendarChip({ when }: { when: { day: number; month: string; overdue?: boolean; today?: boolean } }) {
  return (
    <span className={`day-chip${when.overdue ? " overdue" : ""}${when.today ? " today" : ""}`}>
      <b>{when.day}</b>
      <span>{when.month}</span>
    </span>
  );
}

export const CopyIcon = Copy;
export const CalendarClockIcon = CalendarClock;