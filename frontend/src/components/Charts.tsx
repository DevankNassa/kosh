import { ReactNode } from "react";
import { ASSET_LABEL, date as fmtDate, inrc, pct } from "../format";
import { useTooltip } from "./ui";

const ORDER = ["equity", "debt", "hybrid", "gold", "other"];
export const assetColor = (k: string) => `var(--s-${ORDER.includes(k) ? k : "other"})`;
export const sortAssets = <T extends { name: string }>(rows: T[]) =>
  [...rows].sort((a, b) => ORDER.indexOf(a.name) - ORDER.indexOf(b.name));

type Slice = { name: string; value: number; pct: number };

/** 100% stacked bar of asset classes, with legend. Colours follow the class. */
export function AllocationStack({ rows }: { rows: Slice[] }) {
  const tt = useTooltip();
  const data = sortAssets(rows).filter((r) => r.pct > 0);
  return (
    <div>
      <div className="stackbar" role="img" aria-label={data.map((r) => `${ASSET_LABEL[r.name] || r.name} ${pct(r.pct)}`).join(", ")}>
        {data.map((r) => (
          <div
            key={r.name}
            style={{ width: `${r.pct * 100}%`, background: assetColor(r.name) }}
            onMouseMove={(e) =>
              tt.show(
                e,
                <>
                  <div className="t-title">{ASSET_LABEL[r.name] || r.name}</div>
                  {inrc(r.value)} · {pct(r.pct)}
                </>,
              )
            }
            onMouseLeave={tt.hide}
          />
        ))}
      </div>
      <div className="legend">
        {data.map((r) => (
          <span key={r.name}>
            <i className="dot" style={{ background: assetColor(r.name) }} />
            {ASSET_LABEL[r.name] || r.name} <b style={{ color: "var(--text)" }}>{pct(r.pct, 0)}</b>
          </span>
        ))}
      </div>
      {tt.node}
    </div>
  );
}

/** Horizontal bars with an optional target marker (single series → no legend box). */
export function BarList({
  rows,
  color,
  targets,
  max,
  labelWidth,
}: {
  rows: { name: string; label?: string; value: number; pct: number }[];
  color?: (name: string) => string;
  targets?: Record<string, number | null | undefined>;
  max?: number;
  labelWidth?: number;
}) {
  const tt = useTooltip();
  const top = max ?? Math.max(0.0001, ...rows.map((r) => r.pct), ...Object.values(targets || {}).map((t) => t || 0));
  return (
    <div>
      {rows.map((r) => {
        const t = targets?.[r.name];
        return (
          <div
            className="hbar-row"
            key={r.name}
            style={labelWidth ? { gridTemplateColumns: `${labelWidth}px 1fr 92px` } : undefined}
            onMouseMove={(e) =>
              tt.show(
                e,
                <>
                  <div className="t-title">{r.label || r.name}</div>
                  {inrc(r.value)} · {pct(r.pct)}
                  {t != null && <div>Target {pct(t, 0)}</div>}
                </>,
              )
            }
            onMouseLeave={tt.hide}
          >
            <span className="hbar-label" title={r.label || r.name}>{r.label || r.name}</span>
            <div className="hbar-track">
              <div className="hbar-fill" style={{ width: `${(r.pct / top) * 100}%`, background: color ? color(r.name) : "var(--s-equity)" }} />
              {t != null && <div className="hbar-target" style={{ left: `calc(${(t / top) * 100}% - 1px)` }} title={`Target ${pct(t, 0)}`} />}
            </div>
            <span className="num">{pct(r.pct)}</span>
          </div>
        );
      })}
      {tt.node}
    </div>
  );
}

/** Diverging bars around zero: gains on the right (blue), losses on the left (red). */
export function DivergingBars({
  rows,
  format = (v: number) => inrc(v, { sign: true }),
  onClick,
}: {
  rows: { key: string | number; label: ReactNode; value: number; detail?: ReactNode }[];
  format?: (v: number) => string;
  onClick?: (key: string | number) => void;
}) {
  const tt = useTooltip();
  const max = Math.max(1, ...rows.map((r) => Math.abs(r.value)));
  return (
    <div>
      {rows.map((r) => {
        const w = (Math.abs(r.value) / max) * 50;
        const pos = r.value >= 0;
        return (
          <div
            className="div-row"
            key={r.key}
            style={{ cursor: onClick ? "pointer" : undefined }}
            onClick={() => onClick?.(r.key)}
            onMouseMove={(e) => r.detail && tt.show(e, r.detail)}
            onMouseLeave={tt.hide}
          >
            <span className="hbar-label">{r.label}</span>
            <div className="div-track">
              <div className="div-axis" />
              <div
                className="div-bar"
                style={{
                  left: pos ? "50%" : `${50 - w}%`,
                  width: `${Math.max(w, r.value ? 0.4 : 0)}%`,
                  background: pos ? "var(--pos)" : "var(--neg)",
                  borderRadius: pos ? "0 4px 4px 0" : "4px 0 0 4px",
                }}
              />
            </div>
            <span className={"num " + (r.value > 0 ? "up" : r.value < 0 ? "down" : "")}>{format(r.value)}</span>
          </div>
        );
      })}
      <div className="legend">
        <span><i className="dot" style={{ background: "var(--pos)" }} /> Gain</span>
        <span><i className="dot" style={{ background: "var(--neg)" }} /> Loss</span>
      </div>
      {tt.node}
    </div>
  );
}

/** Single-series line chart (e.g. the yield curve), with hover crosshair. */
export function LineChart({
  points,
  xLabel,
  yFormat,
  xFormat,
  height = 220,
}: {
  points: [number, number][];
  xLabel?: string;
  yFormat: (v: number) => string;
  xFormat: (v: number) => string;
  height?: number;
}) {
  const tt = useTooltip();
  const W = 640;
  const H = height;
  const pad = { l: 48, r: 16, t: 12, b: 34 };
  if (!points.length) return null;
  const xs = points.map((p) => p[0]);
  const ys = points.map((p) => p[1]);
  const x0 = 0;
  const x1 = Math.max(...xs);
  const yMin = Math.min(...ys);
  const yMax = Math.max(...ys);
  const span = Math.max(yMax - yMin, 0.002);
  const lo = yMin - span * 0.2;
  const hi = yMax + span * 0.2;
  const sx = (x: number) => pad.l + ((x - x0) / (x1 - x0 || 1)) * (W - pad.l - pad.r);
  const sy = (y: number) => pad.t + (1 - (y - lo) / (hi - lo)) * (H - pad.t - pad.b);
  const ticks = Array.from({ length: 4 }, (_, i) => lo + ((hi - lo) * (i + 0.5)) / 4);
  const xt = [0, 5, 10, 20, 30, 40].filter((v) => v <= x1);
  const path = points.map((p, i) => `${i ? "L" : "M"}${sx(p[0]).toFixed(1)},${sy(p[1]).toFixed(1)}`).join(" ");
  const last = points[points.length - 1];
  return (
    <div style={{ position: "relative" }}>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="Line chart">
        {ticks.map((t) => (
          <g key={t}>
            <line x1={pad.l} x2={W - pad.r} y1={sy(t)} y2={sy(t)} stroke="var(--grid)" strokeWidth={1} />
            <text x={pad.l - 8} y={sy(t) + 4} textAnchor="end" fontSize={11} fill="var(--text-3)">{yFormat(t)}</text>
          </g>
        ))}
        {xt.map((t, i) => (
          <text
            key={t}
            x={sx(t)}
            y={H - pad.b + 16}
            textAnchor={i === 0 ? "start" : i === xt.length - 1 ? "end" : "middle"}
            fontSize={11}
            fill="var(--text-3)"
          >
            {xFormat(t)}
          </text>
        ))}
        {xLabel && <text x={(W + pad.l) / 2} y={H - 4} textAnchor="middle" fontSize={11} fill="var(--text-2)">{xLabel}</text>}
        <path d={path} fill="none" stroke="var(--s-equity)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
        {points.map((p) => (
          <circle
            key={p[0]}
            cx={sx(p[0])}
            cy={sy(p[1])}
            r={4}
            fill="var(--s-equity)"
            stroke="var(--surface)"
            strokeWidth={2}
          />
        ))}
        {points.map((p) => (
          <rect
            key={"h" + p[0]}
            x={sx(p[0]) - 12}
            y={pad.t}
            width={24}
            height={H - pad.t - pad.b}
            fill="transparent"
            onMouseMove={(e) => tt.show(e, <><div className="t-title">{xFormat(p[0])}</div>{yFormat(p[1])}</>)}
            onMouseLeave={tt.hide}
          />
        ))}
        <text x={sx(last[0]) - 6} y={sy(last[1]) - 10} textAnchor="end" fontSize={11} fill="var(--text)">{yFormat(last[1])}</text>
      </svg>
      {tt.node}
    </div>
  );
}

// Default 2-series colour (a single subject vs the muted broad-market baseline).
const DEFAULT_COLORS = ["var(--s-equity)", "var(--text-3)"];

/** Multiple date-indexed series (rebased to a common base, e.g. 100), with an
 * optional vertical marker for an event date — the market/event chart and the
 * Scenarios "fund families" chart. `colors` lets a caller assign colour by the
 * series' *role* (e.g. always-orange debt, always-yellow gold) rather than by
 * position, since not every series is present for every event.
 * `compact` drops axes/legend for use as a small-multiple tile. */
export function MultiLineChart({
  series,
  eventDate,
  height = 260,
  colors = DEFAULT_COLORS,
  compact = false,
}: {
  series: { label: string; points: { date: string; value: number }[] }[];
  eventDate?: string | null;
  height?: number;
  colors?: string[];
  compact?: boolean;
}) {
  const tt = useTooltip();
  const W = 720;
  const H = height;
  const pad = compact ? { l: 4, r: 4, t: 4, b: 4 } : { l: 44, r: 16, t: 16, b: 28 };
  const allPoints = series.flatMap((s) => s.points);
  if (!allPoints.length) return null;
  const toTs = (d: string) => new Date(d).getTime();
  const xs = allPoints.map((p) => toTs(p.date));
  const ys = allPoints.map((p) => p.value);
  const x0 = Math.min(...xs);
  const x1 = Math.max(...xs);
  const yMin = Math.min(...ys, 100);
  const yMax = Math.max(...ys, 100);
  const span = Math.max(yMax - yMin, 1);
  const lo = yMin - span * 0.1;
  const hi = yMax + span * 0.1;
  const sx = (x: number) => pad.l + ((x - x0) / (x1 - x0 || 1)) * (W - pad.l - pad.r);
  const sy = (y: number) => pad.t + (1 - (y - lo) / (hi - lo)) * (H - pad.t - pad.b);
  const yTicks = Array.from({ length: 4 }, (_, i) => lo + ((hi - lo) * (i + 0.5)) / 4);
  const dates = Array.from(new Set(allPoints.map((p) => p.date))).sort();
  const xTicks = [dates[0], dates[Math.floor(dates.length / 2)], dates[dates.length - 1]];
  const evX = eventDate ? sx(toTs(eventDate)) : null;
  return (
    <div style={{ position: "relative" }}>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="Line chart">
        {!compact && yTicks.map((t) => (
          <g key={t}>
            <line x1={pad.l} x2={W - pad.r} y1={sy(t)} y2={sy(t)} stroke="var(--grid)" strokeWidth={1} />
            <text x={pad.l - 8} y={sy(t) + 4} textAnchor="end" fontSize={11} fill="var(--text-3)">{t.toFixed(0)}</text>
          </g>
        ))}
        {!compact && xTicks.map((d, i) => (
          <text
            key={d}
            x={sx(toTs(d))}
            y={H - pad.b + 16}
            textAnchor={i === 0 ? "start" : i === xTicks.length - 1 ? "end" : "middle"}
            fontSize={11}
            fill="var(--text-3)"
          >
            {fmtDate(d)}
          </text>
        ))}
        {compact && (
          <line x1={pad.l} x2={W - pad.r} y1={sy(100)} y2={sy(100)} stroke="var(--grid)" strokeWidth={1} strokeDasharray="2 2" />
        )}
        {evX != null && (
          <>
            <line x1={evX} x2={evX} y1={pad.t} y2={H - pad.b} stroke="var(--down)" strokeWidth={1.5} strokeDasharray="4 3" />
            {!compact && <text x={evX} y={pad.t - 4} textAnchor="middle" fontSize={10} fill="var(--down)">Event</text>}
          </>
        )}
        {series.map((s, i) => {
          const path = s.points.map((p, j) => `${j ? "L" : "M"}${sx(toTs(p.date)).toFixed(1)},${sy(p.value).toFixed(1)}`).join(" ");
          return <path key={s.label} d={path} fill="none" stroke={colors[i % colors.length]} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />;
        })}
        {!compact && dates.map((d) => (
          <rect
            key={d}
            x={sx(toTs(d)) - 4}
            y={pad.t}
            width={8}
            height={H - pad.t - pad.b}
            fill="transparent"
            onMouseMove={(e) =>
              tt.show(
                e,
                <>
                  <div className="t-title">{fmtDate(d)}</div>
                  {series.map((s) => {
                    const p = s.points.find((pt) => pt.date === d);
                    return p ? <div key={s.label}>{s.label}: {p.value.toFixed(1)}</div> : null;
                  })}
                </>,
              )
            }
            onMouseLeave={tt.hide}
          />
        ))}
      </svg>
      {!compact && (
        <div className="legend">
          {series.map((s, i) => (
            <span key={s.label}><i className="dot" style={{ background: colors[i % colors.length] }} />{s.label}</span>
          ))}
          {eventDate && <span><i className="dot" style={{ background: "var(--down)" }} />Event date</span>}
        </div>
      )}
      {tt.node}
    </div>
  );
}
