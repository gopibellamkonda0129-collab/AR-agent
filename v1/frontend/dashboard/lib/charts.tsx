"use client";

import { useId, useRef, useState } from "react";

export const compactMoney = (n: number) => {
  const a = Math.abs(n);
  if (a >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  if (a >= 1_000) return `$${(n / 1_000).toFixed(0)}k`;
  return `$${n.toFixed(0)}`;
};

/* ------------------------------- ring gauge ------------------------------- */

export function RingGauge({
  value,
  max,
  size = 116,
  stroke = 10,
  tone = "var(--red)",
  center,
  sub,
}: {
  value: number;
  max: number;
  size?: number;
  stroke?: number;
  tone?: string;
  center?: React.ReactNode;
  sub?: string;
}) {
  const pct = max > 0 ? Math.min(1, Math.max(0, value / max)) : 0;
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  return (
    <div className="ring" style={{ width: size, height: size }}>
      <svg width={size} height={size}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="rgba(23,32,72,0.1)" strokeWidth={stroke} />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={tone}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={`${c * pct} ${c}`}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
          className="ring-progress"
        />
      </svg>
      <div className="ring-center">
        {center ?? <b>{Math.round(pct * 100)}%</b>}
        {sub && <span>{sub}</span>}
      </div>
    </div>
  );
}

/* ------------------------------- area spark -------------------------------- */

function smoothLine(pts: { x: number; y: number }[]) {
  if (pts.length < 2) return "";
  let d = `M ${pts[0].x} ${pts[0].y}`;
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[Math.max(0, i - 1)];
    const p1 = pts[i];
    const p2 = pts[i + 1];
    const p3 = pts[Math.min(pts.length - 1, i + 2)];
    const c1x = p1.x + (p2.x - p0.x) / 6;
    const c1y = p1.y + (p2.y - p0.y) / 6;
    const c2x = p2.x - (p3.x - p1.x) / 6;
    const c2y = p2.y - (p3.y - p1.y) / 6;
    d += ` C ${c1x.toFixed(2)} ${c1y.toFixed(2)}, ${c2x.toFixed(2)} ${c2y.toFixed(2)}, ${p2.x.toFixed(2)} ${p2.y.toFixed(2)}`;
  }
  return d;
}

export function AreaChart({
  points,
  height = 90,
  tone = "var(--blue)",
  baseline,
  showDots = true,
}: {
  points: number[];
  height?: number;
  tone?: string;
  baseline?: number;
  showDots?: boolean;
}) {
  const uid = useId().replace(/:/g, "");
  const w = 320;
  const h = height;
  const pad = 8;
  const min = points.length ? Math.min(...points, baseline ?? Infinity) : 0;
  const max = points.length ? Math.max(...points, baseline ?? -Infinity) : 1;
  const span = max - min || 1;
  const pts = points.map((v, i) => ({
    x: pad + (i * (w - pad * 2)) / Math.max(1, points.length - 1),
    y: h - pad - ((v - min) / span) * (h - pad * 2),
  }));
  const line = smoothLine(pts);
  const baseY = baseline == null ? h - 4 : h - pad - ((baseline - min) / span) * (h - pad * 2);
  const area = line ? `${line} L ${pts[pts.length - 1].x} ${baseY} L ${pts[0].x} ${baseY} Z` : "";
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="area-chart" preserveAspectRatio="none">
      <defs>
        <linearGradient id={`g-${uid}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={tone} stopOpacity="0.35" />
          <stop offset="100%" stopColor={tone} stopOpacity="0.02" />
        </linearGradient>
      </defs>
      {baseline != null && <line x1={pad} x2={w - pad} y1={baseY} y2={baseY} stroke="rgba(23,32,72,0.16)" strokeDasharray="3 4" />}
      {area && <path d={area} fill={`url(#g-${uid})`} />}
      {line && <path d={line} fill="none" stroke={tone} strokeWidth={2.2} strokeLinecap="round" className="line-draw" />}
      {showDots &&
        pts.map((p, i) => (
          <circle key={i} className="chart-dot" style={{ animationDelay: `${120 + i * 35}ms` }} cx={p.x} cy={p.y} r={2.4} fill={tone} stroke="#ffffff" strokeWidth={1.2} />
        ))}
    </svg>
  );
}

/* ------------------------------- column chart ------------------------------ */

export function ColumnChart({
  items,
  height = 150,
}: {
  items: { label: string; amount: number; tone?: string; sub?: string }[];
  height?: number;
}) {
  const max = Math.max(...items.map((i) => i.amount), 1);
  const can = items.length > 1;
  return (
    <div className="col-chart" style={{ height }}>
      {items.map((it, i) => {
        const peak = it.amount >= max;
        return (
          <div key={it.label} className="col" title={`${it.label}: ${compactMoney(it.amount)}`}>
            <div className="col-track">
              <div
                className={peak ? "col-fill peak" : "col-fill"}
                style={{
                  height: `${Math.max((it.amount / max) * 100, 2)}%`,
                  background: it.tone || "linear-gradient(180deg, var(--blue), var(--violet))",
                  animationDelay: `${i * 90}ms`,
                }}
              />
            </div>
            <b className="col-val">{compactMoney(it.amount)}</b>
            <span className="col-label">{it.label}</span>
          </div>
        );
      })}
      {can && <div className="col-baseline" />}
    </div>
  );
}

/* ------------------------------- horizontal bars --------------------------- */

export function HBars({
  items,
  max,
}: {
  items: { label: string; value: number; tone?: string; display?: string }[];
  max?: number;
}) {
  const m = max ?? Math.max(...items.map((i) => i.value), 1);
  return (
    <div className="hbars">
      {items.map((it, i) => (
        <div key={it.label} className="hbar">
          <div className="hbar-top">
            <span>{it.label}</span>
            <b>{it.display ?? compactMoney(it.value)}</b>
          </div>
          <div className="hbar-track">
            <div
              className="hbar-fill"
              style={{
                width: `${(it.value / m) * 100}%`,
                background:
                  it.tone ||
                  "linear-gradient(90deg, var(--blue), rgba(111,98,232,0.9))",
                animationDelay: `${i * 70}ms`,
              }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

/* ------------------------- receivables trend chart -------------------------- */

const TREND_W = 820;
const TREND_H = 250;
const TREND_PADX = 14;
const TREND_PADT = 16;
const TREND_PADB = 30;

export function TrendChart({
  labels,
  outstanding,
  overdue,
  collected,
}: {
  labels: string[];
  outstanding: number[];
  overdue: number[];
  collected: number[];
}) {
  const [hover, setHover] = useState<number | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const uid = useId().replace(/:/g, "");
  const n = labels.length;
  const maxV = Math.max(1, ...outstanding, ...overdue, ...collected) * 1.06;

  const xs = (i: number) => TREND_PADX + (i * (TREND_W - TREND_PADX * 2)) / Math.max(1, n - 1);
  const ysx = (v: number) => TREND_H - TREND_PADB - (v / maxV) * (TREND_H - TREND_PADT - TREND_PADB);
  const toPts = (arr: number[]) => arr.map((v, i) => ({ x: xs(i), y: ysx(v) }));
  const baseY = TREND_H - TREND_PADB;

  const outPts = toPts(outstanding);
  const outLine = smoothLine(outPts);
  const area = outLine ? `${outLine} L ${xs(n - 1)} ${baseY} L ${xs(0)} ${baseY} Z` : "";
  const odLine = smoothLine(toPts(overdue));
  const colLine = smoothLine(toPts(collected));

  const step = Math.max(1, Math.ceil(n / 6));
  const xTicks: number[] = [];
  for (let i = 0; i < n; i++) if (i % step === 0) xTicks.push(i);
  if (xTicks[xTicks.length - 1] !== n - 1) xTicks.push(n - 1);

  const gridY = [0.25, 0.5, 0.75].map((t) => TREND_PADT + t * (TREND_H - TREND_PADT - TREND_PADB));

  const onMove = (e: React.MouseEvent) => {
    const el = svgRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    if (rect.width === 0) return;
    const px = e.clientX - rect.left;
    const idx = Math.round((px / rect.width) * (n - 1));
    setHover(Math.max(0, Math.min(n - 1, idx)));
  };

  const hx = `x:${hover ?? -100}`;

  return (
    <div className="trend">
      <svg viewBox={`0 0 ${TREND_W} ${TREND_H}`} ref={svgRef} onMouseMove={onMove} onMouseLeave={() => setHover(null)}>
        <defs>
          <linearGradient id={`to-${uid}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--blue)" stopOpacity="0.3" />
            <stop offset="100%" stopColor="var(--blue)" stopOpacity="0.02" />
          </linearGradient>
        </defs>
        {gridY.map((gy, i) => (
          <line key={i} x1={TREND_PADX} x2={TREND_W - TREND_PADX} y1={gy} y2={gy} stroke="rgba(23,32,72,0.07)" />
        ))}
        {area && <path d={area} fill={`url(#to-${uid})`} className="trend-area" />}
        {outLine && <path d={outLine} stroke="var(--blue)" className="trend-line" style={{ strokeWidth: 2.6 }} />}
        {odLine && <path d={odLine} stroke="var(--red)" className="trend-line" style={{ strokeWidth: 2 }} />}
        {colLine && <path d={colLine} stroke="var(--green)" className="trend-line" style={{ strokeWidth: 2, strokeDasharray: "7 5" }} />}
        {hover != null && (
          <line x1={xs(hover)} x2={xs(hover)} y1={TREND_PADT} y2={baseY} className="trend-rule" />
        )}
        {hover != null &&
          [
            [outstanding[hover], "var(--blue)"],
            [overdue[hover], "var(--red)"],
            [collected[hover], "var(--green)"],
          ].map(([v, tone], i) => (
            <circle key={`${hx}-${i}`} cx={xs(hover)} cy={ysx(Number(v))} r={4} fill="#fff" stroke={tone as string} strokeWidth={2.4} />
          ))}
        {xTicks.map((i) => (
          <text key={i} x={xs(i)} y={TREND_H - 8} textAnchor={i === 0 ? "start" : i === n - 1 ? "end" : "middle"} fontSize={11} fill="var(--faint)" fontWeight={600}>
            {labels[i]}
          </text>
        ))}
      </svg>
      {hover != null && n > 1 && (
        <div
          className="trend-tip"
          style={{
            left: `${(hover / (n - 1)) * 100}%`,
            top: 6,
            transform: `translateX(${hover >= n - 2 ? "-104%" : hover <= 1 ? "4%" : "-50%"})`,
          }}
        >
          <b>{labels[hover]}</b>
          <div className="trend-tip-row">
            <span className="lab">
              <span className="dot" style={{ background: "var(--blue)" }} /> Outstanding
            </span>
            <span className="v">{compactMoney(outstanding[hover])}</span>
          </div>
          <div className="trend-tip-row">
            <span className="lab">
              <span className="dot" style={{ background: "var(--red)" }} /> Overdue
            </span>
            <span className="v">{compactMoney(overdue[hover])}</span>
          </div>
          <div className="trend-tip-row">
            <span className="lab">
              <span className="dot" style={{ background: "var(--green)" }} /> Collected
            </span>
            <span className="v">{compactMoney(collected[hover])}</span>
          </div>
        </div>
      )}
    </div>
  );
}

/* ------------------------- aging buckets (5 rows) -------------------------- */

export function AgingBars({
  buckets,
}: {
  buckets: { label: string; amount: number; tone: string; note?: string }[];
}) {
  const total = Math.max(buckets.reduce((s, b) => s + b.amount, 0), 1);
  return (
    <div className="aging">
      {buckets.map((b, i) => (
        <div key={b.label} className="aging-row">
          <span className="aging-label">{b.label}</span>
          <div className="aging-track">
            <div className="aging-fill" style={{ width: `${(b.amount / total) * 100}%`, background: b.tone, animationDelay: `${i * 80}ms` }} />
          </div>
          <span className="aging-amt">{compactMoney(b.amount)}</span>
          <span className="aging-pct">{((b.amount / total) * 100).toFixed(0)}%</span>
        </div>
      ))}
    </div>
  );
}