"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { fetchActionQueue, fetchCustomers, type Customer } from "../lib/api";
import { usePolling } from "../lib/components";
import { LogoMark } from "../lib/Logo";
import { Bell, Bolt, Building, Inbox, Search, Sparkles, Users } from "../lib/icons";

const GREET = () => {
  const h = new Date().getHours();
  if (h < 6) return { hi: "Working late, Gopi", word: "Let's get you caught up on who owes you." };
  if (h < 12) return { hi: "Good morning, Gopi", word: "Here's every account that needs your attention." };
  if (h < 18) return { hi: "Good afternoon, Gopi", word: "Here's every account that needs your attention." };
  return { hi: "Good evening, Gopi", word: "Here's every account that needs your attention." };
};

const PAGES: { href: string; label: string; icon: React.ReactNode; hint: string }[] = [
  { href: "/overview/", label: "Today", icon: <Bolt size={15} />, hint: "who to chase today" },
  { href: "/actions/", label: "Action Queue", icon: <Sparkles size={15} />, hint: "all recommended actions" },
  { href: "/customers/", label: "Customers", icon: <Users size={15} />, hint: "accounts & timelines" },
  { href: "/invoices/", label: "Invoices", icon: <Building size={15} />, hint: "your ledger" },
  { href: "/inbox/", label: "Inbox", icon: <Inbox size={15} />, hint: "customer email" },
  { href: "/promises/", label: "Promises", icon: <Sparkles size={15} />, hint: "dates customers gave" },
];

export default function Header() {
  const path = usePathname();
  const router = useRouter();
  const queue = usePolling(fetchActionQueue, 60000);
  const word = (() => {
    if (path.startsWith("/overview")) return "Here's who owes you and what to do about it.";
    if (path.startsWith("/actions")) return "Your recommended actions, in priority order.";
    if (path.startsWith("/customers")) return "Accounts, ledgers, and full context.";
    if (path.startsWith("/invoices")) return "Your invoice ledger — the source of truth.";
    if (path.startsWith("/inbox")) return "Customer email the assistant has read.";
    if (path.startsWith("/promises")) return "Every date a customer said they'd pay.";
    if (path.startsWith("/forecast")) return "Expected cash, from promises only.";
    if (path.startsWith("/reports")) return "The weekly receivables picture.";
    if (path.startsWith("/settings")) return "Workspace, connections, and behavior.";
    if (path.startsWith("/admin")) return "Developer diagnostics.";
    return GREET().word;
  })();

  const actions = queue.data?.actions.length ?? 0;
  const [now, setNow] = useState(GREET().hi);
  useEffect(() => {
    setNow(GREET().hi);
  }, []);

  return (
    <header className="topbar">
      <div className="tb-greet">
        <span className="tb-hello">{now}</span>
        <span className="tb-word">{word}</span>
      </div>
      <div className="tb-spacer" />
      <GlobalSearch onPick={() => {}} />
      <div className="tb-actions">
        <Link href="/actions/" className="icon-btn" title={`${actions} action${actions === 1 ? "" : "s"} in queue`} prefetch={false}>
          <Bell size={18} />
          {actions > 0 && <span className="badge-dot" />}
        </Link>
        <span className="avatar-mark" title="Gopi · workspace owner">
          <LogoMark size={32} />
        </span>
      </div>
    </header>
  );
}

function GlobalSearch({ onPick }: { onPick?: () => void }) {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const router = useRouter();
  const customers = usePolling(fetchCustomers, 60000);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  const query = q.trim().toLowerCase();
  const pageHits = query
    ? PAGES.filter((p) => p.label.toLowerCase().includes(query) || p.hint.includes(query))
    : [];
  const custHits: Customer[] = query
    ? (customers.data ?? []).filter(
        (c) =>
          c.customer_name.toLowerCase().includes(query) ||
          (c.contact_email || "").toLowerCase().includes(query)
      )
    : [];
  const showResults = open && query.length > 0 && (pageHits.length > 0 || custHits.length > 0);

  return (
    <div className="tb-search" ref={boxRef}>
      <span className="sic">
        <Search size={16} />
      </span>
      <input
        placeholder="Search customers or pages…"
        value={q}
        onChange={(e) => {
          setQ(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
      />
      {showResults && (
        <div className="tb-results">
          {pageHits.length > 0 && <div className="tr-hint">Pages</div>}
          {pageHits.map((p) => (
            <Link
              key={p.href}
              href={p.href}
              className="tr-row"
              prefetch={false}
              onClick={() => {
                setOpen(false);
                setQ("");
                onPick?.();
              }}
            >
              <span className="nav-ico">{p.icon}</span>
              {p.label}
              <span className="tr-sub">{p.hint}</span>
            </Link>
          ))}
          {custHits.length > 0 && <div className="tr-hint">Customers</div>}
          {custHits.slice(0, 8).map((c) => (
            <button
              key={c.customer_name}
              className="tr-row"
              style={{ background: "transparent", border: 0, width: "100%", textAlign: "left" }}
              onClick={() => {
                setOpen(false);
                setQ("");
                onPick?.();
                router.push(`/customers?open=${encodeURIComponent(c.customer_name)}`);
              }}
            >
              <span className="avatar" style={{ width: 26, height: 26, fontSize: 10 }}>
                {c.customer_name.slice(0, 2).toUpperCase()}
              </span>
              {c.customer_name}
              <span className="tr-sub">{c.contact_email}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}