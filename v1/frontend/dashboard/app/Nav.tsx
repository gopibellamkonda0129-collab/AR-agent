"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAccounts, SyncedInboxStatus, usePolling } from "../lib/components";
import { fetchActionQueue, fetchHealth } from "../lib/api";
import { LogoLockup } from "../lib/Logo";
import { BarChart, Bolt, CalendarClock, FileText, Globe, Inbox, Settings, Sparkles, Target, TrendUp, Users, Cpu } from "../lib/icons";

const LINKS = [
  { href: "/overview/", label: "Today", icon: <Bolt size={17} /> },
  { href: "/actions/", label: "Action Queue", icon: <Sparkles size={17} /> },
  { href: "/customers/", label: "Customers", icon: <Users size={17} /> },
  { href: "/invoices/", label: "Invoices", icon: <FileText size={17} /> },
  { href: "/cash-at-risk/", label: "Cash at Risk", icon: <Target size={17} /> },
  { href: "/inbox/", label: "Inbox", icon: <Inbox size={17} /> },
];

const PLAN = [
  { href: "/promises/", label: "Promises", icon: <CalendarClock size={17} /> },
  { href: "/forecast/", label: "Cash Forecast", icon: <TrendUp size={17} /> },
];

const INFO = [
  { href: "/reports/", label: "Reports", icon: <BarChart size={17} /> },
  { href: "/settings/", label: "Settings", icon: <Settings size={17} /> },
];

const ADMIN_LINK = { href: "/admin/system/", label: "System", icon: <Cpu size={17} /> };

export default function Nav() {
  const path = usePathname();
  const accounts = useAccounts();
  const queue = usePolling(fetchActionQueue, 60000);
  const health = usePolling(fetchHealth, 30000);

  const active = (href: string) =>
    href === "/overview/" ? path === "/overview/" || path === "/" : path.startsWith(href);
  const queueCount = queue.data?.actions.length ?? 0;
  const demo = health.data?.demo ?? true;

  const Row = ({ href, label, icon, count }: { href: string; label: string; icon: React.ReactNode; count?: number }) => (
    <Link key={href} href={href} className={`nav-link${active(href) ? " active" : ""}`} prefetch={false}>
      <span className="nav-ico">{icon}</span>
      {label}
      {count ? <span className="nav-count">{count}</span> : null}
    </Link>
  );

  return (
    <aside className="side">
      <Link href="/overview/" className="brand" prefetch={false}>
        <LogoLockup size={36} />
      </Link>

      <div className="ws-switch" title="Workspace">
        <span className="ws-ico">
          <Globe size={15} />
        </span>
        <span className="ws-name">
          <b>Demo Workspace</b>
          <span>sample data · resets on restart</span>
        </span>
        <span className="ws-caret">▾</span>
      </div>

      {demo && <span className="demo-chip">DEMO — fictional data only</span>}

      <nav className="nav-links">
        <div className="nav-sec">Focus</div>
        {LINKS.map((l) => (
          <Row key={l.href} {...l} count={l.href === "/actions" ? queueCount : undefined} />
        ))}
        <div className="nav-sec">Plan ahead</div>
        {PLAN.map((l) => (
          <Row key={l.href} {...l} />
        ))}
        <div className="nav-sec">Understand</div>
        {INFO.map((l) => (
          <Row key={l.href} {...l} />
        ))}
      </nav>

      <div className="side-foot">
        <div className="ai-status">
          <span className="pulse" />
          <div>
            <b>AI Monitoring</b>
            <span>reading invoices &amp; customer mail</span>
          </div>
        </div>
        <SyncedInboxStatus accounts={accounts} />
        <Row href={ADMIN_LINK.href} label={ADMIN_LINK.label} icon={ADMIN_LINK.icon} />
      </div>
    </aside>
  );
}