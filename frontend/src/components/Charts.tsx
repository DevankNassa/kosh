import { ReactNode } from "react";
import { ASSET_LABEL, inrc, pct } from "../format";
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
        {xt.map((t) => (
          <text key={t} x={sx(t)} y={H - pad.b + 16} textAnchor="middle" fontSize={11} fill="var(--text-3)">{xFormat(t)}</text>
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
