-- AR Agent V1 - Supabase/Postgres schema
-- Apply in the Supabase SQL editor (or `supabase db push`).

create extension if not exists pgcrypto;

create type signal_kind as enum (
  'payment_promise',
  'dispute',
  'missing_invoice',
  'wrong_po',
  'documentation_request',
  'payment_confirmation',
  'bounced_email',
  'info_question',
  'approval_pending',
  'other'
);

create type signal_priority as enum ('low', 'medium', 'high', 'critical');

create table if not exists email_accounts (
  id            uuid primary key default gen_random_uuid(),
  provider      text not null default 'imap',          -- gmail | outlook | imap | demo
  email         text not null,
  display_name  text not null default '',
  provider_config jsonb not null default '{}'::jsonb,  -- oauth/config secrets live here
  status        text not null default 'connected',     -- connected | revoked | error
  auto_sync     boolean not null default true,
  last_sync_at  timestamptz,
  last_sync_status text not null default '',
  last_sync_fetched  int not null default 0,
  last_sync_new_emails int not null default 0,
  last_sync_new_signals int not null default 0,
  created_at    timestamptz not null default now()
);

create table if not exists invoices (
  id                  uuid primary key default gen_random_uuid(),
  customer_name       text not null,
  contact_email       text not null default '',
  invoice_number      text not null default '',
  due_date            date,
  amount_outstanding  numeric(12,2) not null default 0,
  status              text not null default 'open',    -- open | overdue | paid | disputed
  expected_payment_date date,                          -- set from a customer promise
  created_at          timestamptz not null default now()
);
create index if not exists invoices_customer_idx on invoices (customer_name);
create index if not exists invoices_due_idx on invoices (due_date);

create table if not exists messages (
  id          uuid primary key default gen_random_uuid(),
  account_id  uuid not null references email_accounts(id) on delete cascade,
  subject     text not null default '',
  body        text not null default '',
  from_email  text not null default '',
  from_name   text not null default '',
  message_id  text not null default '',
  thread_id   text not null default '',
  received_at timestamptz not null default now(),
  analyzed_at timestamptz,
  created_at  timestamptz not null default now(),
  unique (account_id, message_id)
);
create index if not exists messages_account_idx on messages (account_id, received_at desc);

create table if not exists signals (
  id                 uuid primary key default gen_random_uuid(),
  account_id         uuid not null references email_accounts(id) on delete cascade,
  message_id         uuid references messages(id) on delete cascade,
  customer_name      text not null default '',
  customer_email     text not null default '',
  signal_type        signal_kind not null default 'other',
  priority           signal_priority not null default 'medium',
  confidence         numeric(4,3) not null default 0,
  summary            text not null default '',
  related_invoice    text not null default '',
  promised_date      date,                              -- resolved "pay next Friday"
  promised_amount    numeric(12,2),
  resolved           boolean not null default false,
  resolution_note    text not null default '',
  created_at         timestamptz not null default now(),
  resolved_at        timestamptz
);
create index if not exists signals_open_idx on signals (resolved, priority desc);
create index if not exists signals_promise_idx on signals (signal_type, promised_date)
  where signal_type = 'payment_promise' and resolved = false;

-- team work-queue state per customer (Mark Contacted / Snooze / Pause)
create table if not exists actions_queue (
  id            uuid primary key default gen_random_uuid(),
  customer_name text not null unique,
  status        text not null default 'active',  -- active | contacted | snoozed
  snoozed_until date,
  contacted_at  timestamptz,
  note          text not null default '',
  owner_override text not null default '',        -- manual owner assignment
  paused        boolean not null default false,   -- follow-up control center pause
  paused_until  date,                             -- auto-resume date (null = indefinite)
  paused_reason text not null default '',
  next_action_override text not null default '',  -- team-chosen next action
  created_at    timestamptz not null default now()
);

-- follow-up emails: drafts that pass through human review
create table if not exists followups (
  id            uuid primary key default gen_random_uuid(),
  customer_name text not null,
  draft_type    text not null default 'overdue_reminder',
  subject       text not null default '',
  body          text not null default '',
  status        text not null default 'draft',  -- draft|edited|approved|sent|copied|discarded|no_email
  recipient     text not null default '',
  sent_at       timestamptz,
  context       jsonb not null default '{}'::jsonb,
  created_at    timestamptz not null default now()
);
create index if not exists followups_customer_idx on followups (customer_name, created_at desc);

-- payments received: feed the "Money Recovered" value metric. Only recorded
-- when a user marks an invoice as paid (or imports a payment) - never invented.
create table if not exists payments (
  id            uuid primary key default gen_random_uuid(),
  invoice_id    uuid references invoices(id) on delete set null,
  invoice_number text not null default '',
  customer_name text not null default '',
  amount        numeric(12,2) not null default 0,
  paid_at       date not null default current_date,
  note          text not null default '',
  created_at    timestamptz not null default now()
);
create index if not exists payments_customer_idx on payments (customer_name);
create index if not exists payments_paid_at_idx on payments (paid_at desc);

-- one-click demo dataset (safe, idempotent)
insert into email_accounts (provider, email, display_name)
select 'demo', 'ar@yourcompany.com', 'AR Inbox (demo)'
where not exists (select 1 from email_accounts where email = 'ar@yourcompany.com');