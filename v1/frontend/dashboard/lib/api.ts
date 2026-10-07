export interface Overview {
  total_invoices: number;
  total_outstanding: number;
  open_signals: number;
  by_type: Record<string, number>;
  by_priority: Record<string, number>;
  open_promises: number;
  overdue_promises: number;
  messages_processed: number;
}

export interface Signal {
  id: string;
  customer_name: string;
  customer_email: string;
  from_email?: string;
  message_id?: string;
  signal_type: string;
  priority: string;
  confidence: number;
  summary: string;
  related_invoice: string;
  promised_date: string | null;
  promised_amount: number | null;
  resolved: boolean;
  resolution_note: string;
  created_at: string;
}

export interface PromiseRow {
  signal_id: string;
  customer_name: string;
  customer_email: string;
  promised_date: string;
  promised_amount: number | null;
  related_invoice: string;
  status: "upcoming" | "due_today" | "overdue" | "no_date";
  days_until: number | null;
  summary: string;
  confirmation_sent: boolean;
}

export interface Customer {
  customer_name: string;
  contact_email: string;
  invoice_count: number;
  total_outstanding: number;
  overdue_amount: number;
  avg_days_overdue: number;
  open_signals: number;
  promises: {
    promised_date: string;
    status: string;
    days_overdue: number;
  }[];
}

export interface Account {
  id: string;
  provider: string;
  email: string;
  display_name: string;
  status: string;
  last_sync_at: string | null;
  last_sync_fetched: number;
  last_sync_new_emails: number;
  last_sync_new_signals: number;
  last_sync_status: string;
  created_at: string;
}

export interface Email {
  id: string;
  account_id: string;
  subject: string;
  body: string;
  from_email: string;
  from_name: string;
  message_id: string;
  received_at: string;
  created_at: string;
}

export interface InvoiceProcessStatus {
  invoice_number: string;
  status: string;
  status_label: string;
  stage: string;
  blocker: string | null;
  evidence_status: "KNOWN" | "INFERRED" | "UNKNOWN";
  confidence: number;
  facts: Record<string, { state: "KNOWN" | "INFERRED" | "UNKNOWN"; note: string }>;
  evidence: string[];
  evidence_items?: {
    source: string;
    summary: string;
    evidence_status: string;
    date: string | null;
  }[];
}

export interface Invoice {
  id: string;
  customer_name: string;
  contact_email: string;
  invoice_number: string;
  due_date: string | null;
  amount_outstanding: number;
  status: string;
  process_status?: InvoiceProcessStatus;
  lifecycle?: {
    current_stage: string;
    current_stage_label: string;
    progress: number;
    terminal: string;
  };
  readiness_summary?: {
    verdict: string;
    verdict_label: string;
    passed: number;
    blockers: string[];
  };
}

export interface InvoiceList {
  count: number;
  total_outstanding: number;
  invoices: Invoice[];
}

export interface ActionItem {
  customer_name: string;
  customer_email: string;
  customer_first: string;
  total_outstanding: number;
  overdue_amount: number;
  max_days_overdue: number;
  due_this_week_amount: number;
  invoice_count: number;
  overdue_invoice_count: number;
  primary_invoice_number: string;
  open_signal_count: number;
  open_signal_types: string[];
  latest_signal: {
    signal_type: string;
    summary: string;
    created_at: string | null;
    priority: string;
    resolved: boolean;
    source_email_body: string;
    source_email?: {
      subject: string;
      from_email: string;
      from_name: string;
      received_at: string | null;
    };
  } | null;
  last_response_days: number | null;
  promise: {
    promised_date: string | null;
    promised_amount: number | null;
    status: string | null;
    days_late: number;
    related_invoice: string;
  } | null;
  action: string;
  action_label: string;
  reason: string;
  recommendation_confidence: number;
  suggested_follow_up_date: string;
  draft_type: string;
  priority: string;
  priority_score: number;
  priority_reasons: string[];
  status: string;
  snoozed_until: string | null;
  last_contacted_at: string | null;
  contact_note: string;
  /* collections intelligence (enriched in build_queue) */
  behavior?: {
    reliability_score: number | null;
    reliability_label: string;
    on_time_count: number | null;
    late_count: number | null;
    total_payments: number | null;
    avg_delay_days: number | null;
    promises_kept: number;
    promises_count: number;
    promises_kept_percent: number | null;
    on_time_percent: number | null;
    partial_payments: number;
    promise_breakdown?: {
      outcome: string;
      promised_date: string | null;
      promised_amount: number | null;
      related_invoice: string;
      status_label: string;
      late_days: number | null;
      note: string;
    }[];
  };
  intelligence?: {
    max_days_overdue: number;
    last_response_days: number | null;
    paid_late_count: number;
    open_issue_types: string[];
    risk_reasons: string[];
  };
  chase?: {
    stage: number;
    stage_label: string;
    tone: string;
    approach: string;
    flags: string[];
  };
  why_late?: {
    category: string;
    group: string;
    group_label: string;
    label: string;
    headline: string;
    recommended: string;
  };
  readiness?: {
    status: string;
    label: string;
    tone: string;
    summary: string;
    blocker: string | null;
    checks: { label: string; state: string }[];
  };
  pre_due?: {
    needed: boolean;
    invoice_number: string;
    amount: number;
    due_in_days: number;
    email_example: string;
    checklist: { step: string; state: string; note: string; kind: string }[];
    check_label: string;
  };
  decision_order?: string;
  decision_order_label?: string;
  action_category?: {
    category: string;
    label: string;
  };
  posture?: {
    label: string;
    reason: string;
    confidence?: number;
    evidence_status?: string;
  };
  stuck?: {
    current_stage: string;
    blocker: string | null;
    where: string;
    evidence: string | null;
    evidence_date: string | null;
    confidence: number | null;
    next_action: string;
  };
  process?: {
    current_stage: string;
    blocker: string | null;
    where: string;
    evidence: string | null;
    confidence: number | null;
    next_action: string;
  };
  ownership?: {
    what: string;
    who: string;
    why: string;
    when: string;
    evidence: string;
    manual?: boolean;
    override_value?: string;
  };
  amount_x_days?: number;
  exception_group?: string;
  exception_label?: string;
  comparison_reason?: string;
  agent_rank?: number;
  simple_priority_rank?: number;
  owner_override?: string;
  primary_invoice_id?: string;
  paused?: boolean;
  paused_until?: string | null;
  paused_reason?: string;
  next_action_override?: string;
}

export interface ActionQueue {
  kpis: {
    cash_at_risk: number;
    total_outstanding: number;
    overdue: number;
    due_this_week: number;
    customers_requiring_action: number;
    high_priority_customers: number;
    overdue_promises: number;
    promises_open: number;
    expected_from_promises: number;
    amount_x_days_total: number;
    actions_by_category?: Record<string, number>;
    exceptions?: Record<string, number>;
    exceptions_total?: number;
    pre_due_count?: number;
    pre_due_amount?: number;
    prioritisation: {
      basic: { customer_name: string; amount_x_days: number };
      intelligent: { customer_name: string };
      note: string;
    };
  };
  actions: ActionItem[];
  snoozed: ActionItem[];
  paused: ActionItem[];
}

export interface FollowUp {
  id: string;
  customer_name: string;
  draft_type: string;
  subject: string;
  body: string;
  status: string;
  note?: string;
  current?: boolean;
  context?: {
    priority_reasons: string[];
    recommendation_confidence: number;
    suggested_follow_up_date: string;
    draft_type: string;
    latest_signal?: {
      signal_type: string;
      summary: string;
      priority: string;
      source_email?: {
        subject: string;
        from_email: string;
        from_name: string;
        received_at: string | null;
      };
      source_email_body: string;
    };
  };
}

export interface Forecast {
  as_of: string;
  total_cash: number;
  buckets: {
    key: string;
    label: string;
    amount: number;
    source: string;
    items: {
      customer_name: string;
      amount: number;
      date: string | null;
      status: string;
      source: string;
    }[];
  }[];
}

export interface WeeklyReport {
  generated_at: string;
  week: { start: string; end: string };
  cash_collected: { amount: number; count: number; note: string };
  new_overdue_invoices: { count: number; amount: number; customers: string[] };
  missed_payment_promises: { count: number; amount: number; customers: string[] };
  open_disputes: { count: number; amount: number };
  customers_requiring_escalation: string[];
  largest_overdue_accounts: {
    customer_name: string;
    overdue_amount: number;
    days_overdue: number;
    priority: string;
  }[];
  expected_incoming_payments: number;
  recommended_priorities_next_week: {
    customer_name: string;
    action: string;
    priority: string;
    amount: number;
  }[];
}

export interface PaymentBehavior {
  reliability_score: number | null;
  reliability_label: string;
  on_time_count: number | null;
  late_count: number | null;
  total_payments: number | null;
  avg_delay_days: number | null;
  promises_kept: number;
  promises_count: number;
  promises_missed: number;
  promises_open: number;
  promises_kept_percent: number | null;
  on_time_percent: number | null;
  partial_payments: number;
  last_payment_date: string | null;
  current_overdue: number;
  late_payments: {
    invoice_number: string;
    amount: number;
    paid_at: string;
    due_date: string | null;
    delay_days: number | null;
  }[];
  promise_breakdown?: {
    outcome: string;
    promised_date: string | null;
    promised_amount: number | null;
    related_invoice: string;
    status_label: string;
    late_days: number | null;
    note: string;
  }[];
}

export interface CollectionsIntel {
  overdue_amount: number;
  max_days_overdue: number;
  overdue_invoice_count: number;
  due_this_week_amount: number;
  last_response_days: number | null;
  last_response_label: string;
  missed_promise: {
    promised_date: string | null;
    related_invoice: string;
    promised_amount: number | null;
  } | null;
  paid_late_count: number;
  open_issue_types: string[];
  risk: string;
  risk_score: number;
  risk_reasons: string[];
  recommended_action: string;
  recommended_reason: string;
}

export interface ChaseStrategy {
  stage: number;
  stage_label: string;
  tone: string;
  approach: string;
  steps: string[];
  avoid: string[];
  email: string;
  flags: string[];
}

export interface WhyLate {
  category: string;
  group: string;
  group_label: string;
  label: string;
  headline: string;
  evidence: string | null;
  evidence_date: string | null;
  source_subject: string | null;
  no_confirmed_payment_date: boolean;
  recommended: string;
}

export interface ArProcessStep {
  step: number;
  key: string;
  label: string;
  state: string;
  count: number | null;
  note: string;
}

export interface ArProcessDoc {
  generated_at: string;
  observed: ArProcessStep[];
  recommended: { step: number; label: string; detail: string }[];
  note: string;
}

export interface CustomerArProcess {
  typical: {
    avg_delay_days: number | null;
    on_time_percent: number | null;
    promises_kept_percent: number | null;
    promises_count: number;
    promises_missed: number;
    partial_payments: number;
  };
  requirements: {
    po_required: string;
    po_evidence: string;
    ap_contact: string;
    approval_process: string;
    approval_evidence: string;
    documentation: string;
    documentation_evidence: string;
    known_invoice_issues: string[];
  };
  current: {
    current_stage: string;
    blocker: string | null;
    where: string;
    next_action: string;
    confidence: number | null;
  };
  posture: {
    label: string;
    reason: string;
    confidence?: number;
    evidence_status?: string;
  };
}

export interface TimelineEvent {
  date: string;
  kind: string;
  title: string;
  detail: string;
  topics?: string[];
}

export interface CustomerIntelligence {
  customer_name: string;
  behavior: PaymentBehavior;
  collections: CollectionsIntel;
  strategy: ChaseStrategy;
  why_late: WhyLate;
  readiness: {
    status: string;
    label: string;
    tone: string;
    summary: string;
    blocker: string | null;
    checks: { label: string; state: string }[];
  };
  pre_due: {
    needed: boolean;
    invoice_number: string;
    amount: number;
    due_in_days: number;
    email_example: string;
    checklist: { step: string; state: string; note: string; kind: string }[];
    check_label: string;
  };
  decision_order: string;
  ownership: { what: string; who: string; why: string; when: string; evidence?: string };
  ar_process: CustomerArProcess;
  timeline: TimelineEvent[];
}

export interface CustomerDetail {
  customer_name: string;
  contact_email: string;
  invoice_count: number;
  total_outstanding: number;
  overdue_amount: number;
  max_days_overdue: number;
  invoices: Invoice[];
  signals: Signal[];
  emails: Email[];
  promises: {
    promised_date: string;
    promised_amount: number | null;
    status: string;
    days_late: number;
    summary: string;
    signal_id: string;
  }[];
  recommended_action: {
    action: string;
    action_label: string;
    reason: string;
    recommendation_confidence: number;
    suggested_follow_up_date: string;
    draft_type: string;
    priority: string;
    priority_score: number;
    priority_reasons: string[];
  };
  behavior: PaymentBehavior;
  collections: CollectionsIntel;
  strategy: ChaseStrategy;
  why_late: WhyLate;
  readiness: {
    status: string;
    label: string;
    tone: string;
    summary: string;
    blocker: string | null;
    checks: { label: string; state: string }[];
  };
  pre_due: {
    needed: boolean;
    invoice_number: string;
    amount: number;
    due_in_days: number;
    email_example: string;
    checklist: { step: string; state: string; note: string; kind: string }[];
    check_label: string;
  };
  decision_order: string;
  ownership: { what: string; who: string; why: string; when: string; evidence?: string };
  ar_process: CustomerArProcess;
  timeline: TimelineEvent[];
}

export interface Health {
  ok: boolean;
  demo: boolean;
  llm: boolean;
  supabase: boolean;
  sync_interval_seconds: number;
}

export interface SyncResult {
  account_id: string;
  fetched: number;
  analyzed: number;
  new_emails: number;
  new_signals: number;
  last_sync_at: string;
}

export interface InvoiceImportResult {
  imported: number;
  files: number;
  customers: string[];
  warnings: string[];
}

export interface MoneyRecovered {
  total: number;
  this_month: number;
  last_month: number;
  this_month_label: string;
}

export interface Payment {
  id: string;
  invoice_id: string;
  invoice_number: string;
  customer_name: string;
  amount: number;
  paid_at: string;
  note: string;
  created_at: string;
}

/* ---- Cash-at-Risk view (additive to the existing risk score) ---- */
export interface CashRiskRow {
  invoice_number: string;
  customer_name: string;
  amount_outstanding: number;
  due_date: string | null;
  days_overdue: number;
  status: string;
  status_label: string;
  stage: string;
  blocker: string | null;
  evidence_status: string;
  risk_weight: number;
  band: string;
  band_label: string;
  pre_due: boolean;
  next_action: string;
  reason: string;
  readiness_verdict: string;
  readiness_label: string;
  reliability: string;
  missed_promises: number;
  owner: string;
  agent_rank: number;
  primary_invoice_id: string;
}

export interface CashRiskBand {
  band: string;
  label: string;
  count: number;
  risk_value: number;
}

export interface CashRiskCustomer {
  customer_name: string;
  invoice_count: number;
  outstanding: number;
  overdue_amount: number;
  worst_days_overdue: number;
  risk_weight: number;
  bands: Record<string, number>;
  blockers: string[];
}

export interface CashRiskView {
  as_of: string;
  totals: {
    open_invoices: number;
    open_amount: number;
    overdue_invoices: number;
    overdue_amount: number;
    weighted_risk: number;
    critical_invoices: number;
    critical_amount: number;
    blocked_cash: number;
    blocked_invoices: number;
  };
  by_band: CashRiskBand[];
  customers: CashRiskCustomer[];
  rows: CashRiskRow[];
}

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8000";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    let detail = body;
    try {
      detail = JSON.parse(body).detail || body;
    } catch {
      /* keep raw */
    }
    throw new Error(`${res.status}: ${detail}`);
  }
  return res.json();
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    let detail = text;
    try {
      detail = JSON.parse(text).detail || text;
    } catch {
      /* keep raw */
    }
    throw new Error(`${res.status}: ${detail}`);
  }
  return res.json();
}

export async function fetchOverview(): Promise<Overview> {
  return get<Overview>("/customers/overview");
}
export async function fetchAccounts(): Promise<Account[]> {
  return get<Account[]>("/accounts");
}
export async function fetchSignals(): Promise<Signal[]> {
  return get<Signal[]>("/signals?resolved=false");
}
export async function fetchPromises(): Promise<PromiseRow[]> {
  return get<PromiseRow[]>("/customers/promises");
}
export async function fetchCustomers(): Promise<Customer[]> {
  return get<Customer[]>("/customers");
}
export async function fetchEmails(accountId?: string): Promise<Email[]> {
  return get<Email[]>(`/emails/messages${accountId ? `?account_id=${encodeURIComponent(accountId)}&limit=50` : "?limit=50"}`);
}
export async function fetchInvoices(): Promise<InvoiceList> {
  return get<InvoiceList>("/invoices");
}
export async function fetchHealth(): Promise<Health> {
  return get<Health>("/health");
}
export async function gmailAuthUrl(email: string): Promise<{ auth_url: string; state: string }> {
  return get<{ auth_url: string; state: string }>(`/gmail/start?email=${encodeURIComponent(email)}`);
}

/* ---- ACTION QUEUE ---- */
export async function fetchActionQueue(): Promise<ActionQueue> {
  return get<ActionQueue>("/actions");
}

export async function markContacted(customer: string, note: string): Promise<{ status: string }> {
  return post<{ status: string }>(`/actions/${encodeURIComponent(customer)}/contacted`, { note });
}
export async function snoozeCustomer(customer: string, until: string): Promise<{ status: string }> {
  return post<{ status: string }>(`/actions/${encodeURIComponent(customer)}/snooze`, { until });
}
export async function reactivateCustomer(customer: string): Promise<{ status: string }> {
  return post<{ status: string }>(`/actions/${encodeURIComponent(customer)}/reactivate`);
}

/* ---- FOLLOW-UPS ---- */
export async function getFollowUp(customer: string): Promise<FollowUp> {
  return get<FollowUp>(`/followups/${encodeURIComponent(customer)}`);
}
export async function saveFollowUp(customer: string, draft: {
  draft_type: string;
  subject: string;
  body: string;
}): Promise<FollowUp> {
  return post<FollowUp>(`/followups/${encodeURIComponent(customer)}`, draft);
}
export async function approveSendFollowUp(id: string): Promise<{
  approved: boolean;
  sent: boolean;
  message: string;
}> {
  return post<{ approved: boolean; sent: boolean; message: string }>(`/followups/${id}/approve-send`, { send: true });
}
export async function copyFollowUp(id: string): Promise<{ status: string }> {
  return post<{ status: string }>(`/followups/${id}/copy`);
}
export async function discardFollowUp(id: string): Promise<{ status: string }> {
  return post<{ status: string }>(`/followups/${id}/discard`);
}

/* ---- FORECAST + REPORT ---- */
export async function fetchForecast(): Promise<Forecast> {
  return get<Forecast>("/forecast");
}
export async function fetchWeeklyReport(): Promise<WeeklyReport> {
  return get<WeeklyReport>("/reports/weekly");
}
export async function fetchArProcess(): Promise<ArProcessDoc> {
  return get<ArProcessDoc>("/reports/ar-process");
}

/* ---- customer detail ---- */
export async function fetchCustomerDetail(name: string): Promise<CustomerDetail> {
  return get<CustomerDetail>(`/customers/${encodeURIComponent(name)}`);
}

/* ---- customer collections intelligence ---- */
export async function fetchCustomerIntelligence(name: string): Promise<CustomerIntelligence> {
  return get<CustomerIntelligence>(`/customers/intelligence/${encodeURIComponent(name)}`);
}

/* ---- inbox / accounts / invoices ---- */
export async function connectInbox(input: {
  provider: string;
  email: string;
  display_name: string;
  config: Record<string, string>;
}): Promise<Account> {
  return post<Account>("/accounts", input);
}
export async function syncAccount(id: string): Promise<SyncResult> {
  return post<SyncResult>(`/accounts/${id}/sync`);
}
export async function importInvoices(files: File[]): Promise<InvoiceImportResult> {
  const fd = new FormData();
  files.forEach((f) => fd.append("files", f));
  const res = await fetch(`${API_BASE}/invoices/import`, { method: "POST", body: fd });
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
  return res.json();
}
export async function markInvoicePaid(
  invoiceId: string,
  input: { amount: number; paid_at?: string; note?: string },
): Promise<Invoice> {
  return post<Invoice>(`/invoices/${invoiceId}/mark-paid`, input);
}
export async function fetchPayments(): Promise<Payment[]> {
  return get<Payment[]>("/invoices/payments");
}
export async function fetchMoneyRecovered(): Promise<MoneyRecovered> {
  return get<MoneyRecovered>("/reports/money-recovered");
}
export async function clearInvoices(): Promise<{ removed: number }> {
  return post<{ removed: number }>("/invoices/clear");
}
export async function resolveSignal(id: string, note: string): Promise<Signal> {
  return post<Signal>(`/signals/${id}/resolve`, { resolved: true, note });
}

/* ---- Cash-at-Risk ---- */
export async function fetchCashRisk(sort: "weight" | "agent" = "weight"): Promise<CashRiskView> {
  return get<CashRiskView>(`/invoices/cash-at-risk?sort=${sort}`);
}

/* ---- Owner override ---- */
export async function setCustomerOwner(customer: string, owner: string): Promise<{ status: string; manual: boolean }> {
  return post<{ status: string; manual: boolean }>(
    `/actions/${encodeURIComponent(customer)}/owner`,
    { owner },
  );
}

/* ---- Follow-up control center (pause / resume / cancel / next-action) ---- */
export async function pauseCustomer(
  customer: string,
  input: { until?: string; reason?: string },
): Promise<{ paused: boolean; until: string | null; reason: string }> {
  return post<{ paused: boolean; until: string | null; reason: string }>(
    `/actions/${encodeURIComponent(customer)}/pause`,
    { until: input.until || "", reason: input.reason || "" },
  );
}
export async function resumeCustomer(customer: string): Promise<{ paused: boolean; status: string }> {
  return post<{ paused: boolean; status: string }>(`/actions/${encodeURIComponent(customer)}/resume`);
}
export async function cancelChase(
  customer: string,
  reason: string,
): Promise<{ paused: boolean; cancelled: boolean; reason: string }> {
  return post<{ paused: boolean; cancelled: boolean; reason: string }>(
    `/actions/${encodeURIComponent(customer)}/cancel-chase`,
    { until: "", reason },
  );
}
export async function setNextAction(
  customer: string,
  action: string,
): Promise<{ action: string; manual: boolean; status: string }> {
  return post<{ action: string; manual: boolean; status: string }>(
    `/actions/${encodeURIComponent(customer)}/next-action`,
    { action },
  );
}
export async function fetchPausedCustomers(): Promise<{ paused: { customer_name: string; paused_until: string | null; paused_reason: string }[]; count: number }> {
  return get(`/actions/paused`);
}

/* ---- Invoice action panel ---- */
export interface InvoiceLifecycleStage {
  key: string;
  label: string;
  evidence_status: "KNOWN" | "INFERRED" | "UNKNOWN";
  note: string;
  date: string | null;
  state: "done" | "current" | "upcoming" | "blocked";
  blocker?: string;
}

export interface InvoiceLifecycle {
  invoice_number: string;
  status: string;
  status_label: string;
  current_stage: string;
  current_stage_label: string;
  progress: number;
  terminal: string;
  stages: InvoiceLifecycleStage[];
}

export interface SendReadinessCheck {
  key: string;
  label: string;
  status: "PASS" | "WARNING" | "BLOCKED" | "UNKNOWN";
  evidence: string;
  note: string;
  verify: string;
}

export interface ReminderSafety {
  verdict: string;
  verdict_label: string;
  recommended_action: string;
  note: string;
  product_rule: boolean;
  checks: { key: string; label: string; outcome: boolean; evidence: string; note: string }[];
}

export interface PaymentReadinessSignal {
  key: string;
  label: string;
  weight: number;
  value: string;
  score: number;
  reason: string;
}

export interface InvoiceActionPanel {
  invoice_number: string;
  customer_name: string;
  amount_outstanding: number;
  due_date: string | null;
  invoice_date: string | null;
  process_status: InvoiceProcessStatus;
  lifecycle: InvoiceLifecycle;
  readiness: {
    invoice_number: string;
    customer_name: string;
    checks: SendReadinessCheck[];
    passed: number;
    warning: number;
    unknown: number;
    blocked: number;
    total: number;
    verdict: string;
    verdict_label: string;
    blockers: string[];
    verify_before_send: string[];
  };
  reminder_safety: ReminderSafety;
  payment_readiness_score: {
    score: number;
    label: string;
    tone: string;
    max_score: number;
    method: string;
    signals: PaymentReadinessSignal[];
  };
  recommended_action: {
    action: string;
    action_label: string;
    reason: string;
    confidence: number;
    priority: string;
    draft_type: string;
    exception_group: string;
    exception_label: string;
    owner: string;
    chase_stage: string;
    suggested_follow_up: string | null;
  };
  control: {
    primary_invoice_id: string;
    paused: boolean;
    paused_until: string | null;
    paused_reason: string;
    next_action_override: string;
    owner_override: string;
    snoozed_until: string | null;
    status: string;
  };
}

export async function fetchInvoiceActionPanel(invoiceId: string): Promise<InvoiceActionPanel> {
  return get<InvoiceActionPanel>(`/invoices/${encodeURIComponent(invoiceId)}/action-panel`);
}

export const PRIO_RANK: Record<string, number> = { critical: 4, high: 3, medium: 2, low: 1 };

export const TYPE_LABEL: Record<string, string> = {
  payment_promise: "Payment promise",
  dispute: "Dispute",
  missing_invoice: "Missing invoice",
  wrong_po: "Wrong PO",
  documentation_request: "Docs requested",
  payment_confirmation: "Payment confirmed",
  bounced_email: "Bounced email",
  info_question: "Question",
  approval_pending: "Approval pending",
  other: "Other",
};

export const PASSWORD_SENTINEL = "•••••••";