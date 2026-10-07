"use client";

import { useMemo, useState } from "react";
import {
  fetchActionQueue,
  markContacted,
  reactivateCustomer,
  resumeCustomer,
  type ActionItem,
} from "../../lib/api";
import {
  ActionItemView,
  ControlCenterModal,
  ExceptionBadge,
  FilterChips,
  FollowUpComposer,
  Modal,
  PageTitle,
  Skeleton,
  SnoozeModal,
  fmtDate,
  usePolling,
} from "../../lib/components";
import { Sparkles } from "../../lib/icons";

const EXCEPTION_ORDER = [
  "missed_promise", "dispute", "blocked", "verify",
  "pre_due", "no_response", "overdue", "question", "routine",
];

const EXCEPTION_LABEL: Record<string, string> = {
  missed_promise: "Missed promise",
  dispute: "Dispute resolution",
  blocked: "Blocked in their process",
  verify: "Verify reported payment",
  pre_due: "Confirm before due",
  no_response: "Overdue — no response",
  overdue: "Overdue cash",
  question: "Question / info request",
  routine: "Routine",
};

export default function ActionsPage() {
  const queue = usePolling(fetchActionQueue, 20000);
  const [tab, setTab] = useState<"all" | "critical" | "high" | "medium" | "low">("all");
  const [reviewing, setReviewing] = useState<ActionItem | null>(null);
  const [snoozing, setSnoozing] = useState<ActionItem | null>(null);
  const [contacting, setContacting] = useState<ActionItem | null>(null);
  const [controlling, setControlling] = useState<ActionItem | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  const showPaused = queue.data?.paused?.length ? queue.data.paused.length > 0 : false;

  const resumePaused = async (name: string) => {
    try {
      await resumeCustomer(name);
      queue.reload();
    } catch (e) {
      setMsg(String(e));
    }
  };

  const filtered = useMemo(() => {
    const all = queue.data?.actions ?? [];
    if (tab === "all") return all;
    return all.filter((a) => a.priority === tab);
  }, [queue.data, tab]);

  const counts = useMemo(() => {
    const all = queue.data?.actions ?? [];
    return {
      all: all.length,
      critical: all.filter((a) => a.priority === "critical").length,
      high: all.filter((a) => a.priority === "high").length,
      medium: all.filter((a) => a.priority === "medium").length,
      low: all.filter((a) => a.priority === "low").length,
    };
  }, [queue.data]);

  const chips = [
    { key: "all", label: "All", count: counts.all, active: tab === "all", onClick: () => setTab("all") },
    { key: "critical", label: "Critical", count: counts.critical, active: tab === "critical", onClick: () => setTab("critical"), tone: "var(--red)" },
    { key: "high", label: "High", count: counts.high, active: tab === "high", onClick: () => setTab("high"), tone: "var(--amber)" },
    { key: "medium", label: "Medium", count: counts.medium, active: tab === "medium", onClick: () => setTab("medium"), tone: "var(--blue)" },
    { key: "low", label: "Low", count: counts.low, active: tab === "low", onClick: () => setTab("low"), tone: "var(--green)" },
  ];

  const grouped = useMemo(() => {
    if (tab !== "all") return null;
    const map = new Map<string, ActionItem[]>();
    for (const a of filtered) {
      const g = a.exception_group || "routine";
      if (!map.has(g)) map.set(g, []);
      map.get(g)!.push(a);
    }
    return EXCEPTION_ORDER.filter((k) => map.has(k)).map((k) => ({ key: k, label: EXCEPTION_LABEL[k] || k, items: map.get(k)! }));
  }, [filtered, tab]);

  const confirmContacted = async (item: ActionItem) => {
    setBusy(true);
    setMsg("");
    try {
      await markContacted(item.customer_name, note || "Marked contacted from Action Queue.");
      queue.reload();
      setContacting(null);
      setNote("");
    } catch (e) {
      setMsg(String(e));
    } finally {
      setBusy(false);
    }
  };

  const reactivate = async (item: ActionItem) => {
    try {
      await reactivateCustomer(item.customer_name);
      queue.reload();
    } catch (e) {
      setMsg(String(e));
    }
  };

  return (
    <div className="page-body">
      <PageTitle
        title="Action Queue"
        sub="Every customer that needs chasing today — with the reason why and a draft follow-up you control."
        eyebrow="Focus"
      />
      {queue.error && <div className="banner err">{queue.error}</div>}
      {msg && <div className="banner err">{msg}</div>}

      <div className="card">
        <div className="hd-inline">
          <h2>
            {tab === "all" ? "Action required" : `${tab} priority`}
            <span className="count">{filtered.length}</span>
          </h2>
          <FilterChips items={chips} />
        </div>
        {queue.loading && !queue.data ? (
          <div className="sk-list">
            <Skeleton lines={5} h={92} br={14} />
          </div>
        ) : filtered.length === 0 ? (
          <div className="empty-hint">
            <b>Nothing here.</b>
            <div className="muted">
              {tab === "all"
                ? "The queue is clear — a customer likely just paid."
                : "Nothing in this bucket. Try another filter."}
            </div>
          </div>
        ) : grouped ? (
          <div className="ex-sections">
            {grouped.map((sec) => (
              <div key={sec.key} className="ex-section">
                <div className="ex-section-head">
                  <ExceptionBadge group={sec.key} label={sec.label} />
                  <span className="count">{sec.items.length}</span>
                </div>
                <div className="ex-section-items">
                  {sec.items.map((item) => (
                    <ActionItemView
                      key={item.customer_name}
                      item={item}
                      onReview={() => setReviewing(item)}
                      onContacted={() => setContacting(item)}
                      onSnooze={() => setSnoozing(item)}
                      onReactivate={() => reactivate(item)}
                      onOwnerChanged={() => queue.reload()}
                      onControl={() => setControlling(item)}
                    />
                  ))}
                </div>
              </div>
            ))}
          </div>
        ) : (
          filtered.map((item) => (
            <ActionItemView
              key={item.customer_name}
              item={item}
              onReview={() => setReviewing(item)}
              onContacted={() => setContacting(item)}
              onSnooze={() => setSnoozing(item)}
              onReactivate={() => reactivate(item)}
              onOwnerChanged={() => queue.reload()}
              onControl={() => setControlling(item)}
            />
          ))
        )}
      </div>

      {showPaused && (
        <div className="card">
          <div className="hd-inline">
            <h2>
              Paused / chase cancelled
              <span className="count">{queue.data?.paused?.length}</span>
            </h2>
            <span className="muted small">Held by the team — not chased until resumed.</span>
          </div>
          <div className="paused-list">
            {(queue.data?.paused ?? []).map((p) => (
              <div key={p.customer_name} className="paused-row">
                <span className="chip chip-red">paused{p.paused_until ? ` until ${fmtDate(p.paused_until)}` : " indefinitely"}</span>
                <b>{p.customer_name}</b>
                <span className="muted small">{p.paused_reason || "no reason recorded"}</span>
                <button className="btn small ghost" onClick={() => resumePaused(p.customer_name)}>
                  Resume chasing
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {queue.data?.kpis && (queue.data.kpis.exceptions_total ?? 0) > 0 && (
        <div className="kpi-row kpi-ex-row">
          <div className="kpi">
            <div className="k-label">Exceptions</div>
            <div className="k-num">{queue.data.kpis.exceptions_total}</div>
            <div className="k-sub">beyond routine chasing</div>
          </div>
          {queue.data.kpis.pre_due_count != null && queue.data.kpis.pre_due_count > 0 && (
            <div className="kpi">
              <div className="k-label">Pre-due readiness</div>
              <div className="k-num">{queue.data.kpis.pre_due_count}</div>
              <div className="k-sub">due within 7d</div>
            </div>
          )}
          {queue.data.kpis.overdue_promises != null && queue.data.kpis.overdue_promises > 0 && (
            <div className="kpi">
              <div className="k-label">Missed promises</div>
              <div className="k-num">{queue.data.kpis.overdue_promises}</div>
              <div className="k-sub">promise date has passed</div>
            </div>
          )}
        </div>
      )}

      {reviewing && <FollowUpComposer item={reviewing} onClose={() => setReviewing(null)} onChanged={() => queue.reload()} />}
      {snoozing && <SnoozeModal item={snoozing} onClose={() => setSnoozing(null)} onSnoozed={() => queue.reload()} />}
      {controlling && <ControlCenterModal item={controlling} onClose={() => setControlling(null)} onChanged={() => queue.reload()} />}
      {contacting && (
        <Modal title={`Mark contacted · ${contacting.customer_name}`} onClose={() => setContacting(null)}>
          <div className="field">
            <label htmlFor="cnote">What did you do?</label>
            <input id="cnote" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Phoned them — they'll wire it Friday." />
          </div>
          <div className="row-btns">
            <button className="btn" disabled={busy} onClick={() => confirmContacted(contacting)}>
              Confirm
            </button>
            <button className="btn ghost" onClick={() => setContacting(null)}>
              Cancel
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}
