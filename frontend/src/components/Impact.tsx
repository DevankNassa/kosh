import { useState } from "react";
import { Link } from "react-router-dom";
import { ASSET_LABEL, inr, inrc, pct, tone } from "../format";
import { DivergingBars } from "./Charts";
import { InstrumentSearch } from "./InstrumentSearch";
import { Stat, useApi } from "./ui";

export type Shock = {
  yield_shift_bps?: number;
  spread_bps?: number;
  rating_buckets?: string[];
  equity_move_pct?: number;
  gold_move_pct?: number;
  default_recovery_pct?: number;
  filter?: { isins?: string[]; issuer_keys?: string[]; sector?: string; not_sector?: string };
};

const RATINGS = ["AAA", "AA", "A", "BBB", "Below BBB", "Unrated / unknown"];

/** Builds a shock: what moved, and (optionally) which sector / issuers it touches. */
export function ShockBuilder({ value, onChange }: { value: Shock; onChange: (s: Shock) => void }) {
  const { data: sectors } = useApi<string[]>("/api/sectors");
  const [targets, setTargets] = useState<{ name: string; isin: string }[]>([]);
  const scope = value.filter?.sector ? "sector" : value.filter?.issuer_keys?.length ? "issuer" : "market";
  const set = (patch: Partial<Shock>) => {
    const next = { ...value, ...patch };
    (Object.keys(next) as (keyof Shock)[]).forEach((k) => {
      const v = next[k];
      if (v === undefined || v === null || (typeof v === "number" && (Number.isNaN(v) || v === 0)) || (Array.isArray(v) && !v.length)) delete next[k];
    });
    onChange(next);
  };
  const numIn = (k: keyof Shock, label: string, step = 1) => (
    <label className="field">
      {label}
      <input type="number" step={step} value={(value[k] as number | undefined) ?? ""}
        onChange={(e) => set({ [k]: e.target.value === "" ? undefined : Number(e.target.value) } as Partial<Shock>)} />
    </label>
  );
  const setScope = (s: string) => {
    setTargets([]);
    if (s === "market") set({ filter: undefined });
    if (s === "sector") set({ filter: { sector: sectors?.[0] || "Financial Services" } });
    if (s === "issuer") set({ filter: { issuer_keys: [] } });
  };
  return (
    <div className="stack" style={{ gap: 12 }}>
      <div className="form-grid">
        {numIn("yield_shift_bps", "G-sec yield change (bps)", 5)}
        {numIn("equity_move_pct", "Share price move (%)", 0.5)}
        {numIn("spread_bps", "Corporate bond spread change (bps)", 5)}
        {numIn("gold_move_pct", "Gold price move (%)", 0.5)}
      </div>
      {value.spread_bps ? (
        <div className="row small">
          <span className="muted">Spread change applies to:</span>
          {RATINGS.map((r) => {
            const on = !value.rating_buckets || value.rating_buckets.includes(r);
            return (
              <label key={r} className="row" style={{ gap: 4 }}>
                <input type="checkbox" checked={on} onChange={() => {
                  const cur = value.rating_buckets || RATINGS;
                  const next = on ? cur.filter((x) => x !== r) : [...cur, r];
                  set({ rating_buckets: next.length === RATINGS.length ? undefined : next });
                }} />
                {r}
              </label>
            );
          })}
        </div>
      ) : null}
      <div>
        <div className="small muted" style={{ marginBottom: 6 }}>Which holdings does it touch?</div>
        <div className="seg">
          {[["market", "Market-wide"], ["sector", "A sector"], ["issuer", "Specific companies"]].map(([k, l]) => (
            <button key={k} className={scope === k ? "active" : ""} onClick={() => setScope(k)}>{l}</button>
          ))}
        </div>
      </div>
      {scope === "sector" && (
        <select value={value.filter?.sector} onChange={(e) => set({ filter: { sector: e.target.value } })}>
          {(sectors || []).map((s) => <option key={s}>{s}</option>)}
        </select>
      )}
      {scope === "issuer" && (
        <div>
          <InstrumentSearch
            placeholder="Add a company (its shares and bonds are both matched)"
            onPick={(h) => {
              const key = h.isin.slice(0, 7);
              const keys = Array.from(new Set([...(value.filter?.issuer_keys || []), key]));
              setTargets([...targets, { name: h.name, isin: h.isin }]);
              set({ filter: { issuer_keys: keys } });
            }}
          />
          <div className="row" style={{ marginTop: 6 }}>
            {(value.filter?.issuer_keys || []).map((k) => (
              <span key={k} className="badge info">
                {targets.find((t) => t.isin.startsWith(k))?.name || k}
                <button className="ghost" style={{ padding: 0 }} onClick={() => set({ filter: { issuer_keys: value.filter!.issuer_keys!.filter((x) => x !== k) } })}>✕</button>
              </span>
            ))}
          </div>
          <div className="row small" style={{ marginTop: 8 }}>
            <label className="row" style={{ gap: 4 }}>
              <input type="checkbox" checked={value.default_recovery_pct != null}
                onChange={(e) => set({ default_recovery_pct: e.target.checked ? 40 : undefined })} />
              Treat as a default on their bonds, recovering
            </label>
            {value.default_recovery_pct != null && (
              <input type="number" value={value.default_recovery_pct} style={{ width: 70 }}
                onChange={(e) => onChange({ ...value, default_recovery_pct: Number(e.target.value) })} />
            )}
            {value.default_recovery_pct != null && "%"}
          </div>
        </div>
      )}
      <p className="small faint">
        Bonds move by duration and convexity; debt funds by their category's typical duration; hybrid funds by their typical equity share. Mutual fund holdings are not looked through to individual companies yet.
      </p>
    </div>
  );
}

function describeOneShock(s: Shock): string {
  const parts = [];
  if (s.yield_shift_bps) parts.push(`yields ${s.yield_shift_bps > 0 ? "+" : ""}${s.yield_shift_bps} bps`);
  if (s.spread_bps) parts.push(`spreads ${s.spread_bps > 0 ? "+" : ""}${s.spread_bps} bps`);
  if (s.equity_move_pct) parts.push(`shares ${s.equity_move_pct > 0 ? "+" : ""}${s.equity_move_pct}%`);
  if (s.gold_move_pct) parts.push(`gold ${s.gold_move_pct > 0 ? "+" : ""}${s.gold_move_pct}%`);
  if (s.default_recovery_pct != null) parts.push(`default, ${s.default_recovery_pct}% recovery`);
  const f = s.filter;
  const scope = f?.sector ? ` · ${f.sector}` : f?.issuer_keys?.length ? ` · ${f.issuer_keys.length} issuer(s)` : f?.isins?.length ? " · selected securities" : f?.not_sector ? ` · rest of the market (ex ${f.not_sector})` : " · market-wide";
  return (parts.join(", ") || "no change") + scope;
}

export function describeShock(s: Shock | Shock[]): string {
  return Array.isArray(s) ? s.map(describeOneShock).join("; ") : describeOneShock(s);
}

/** Book-level impact: totals, per-client bars, and expandable holdings. */
export function ImpactView({ impact }: { impact: any }) {
  const [open, setOpen] = useState<number | null>(null);
  return (
    <div className="stack">
      <div className="grid g4">
        <Stat label="Clients exposed" value={`${impact.clients_exposed} of ${impact.clients_total}`} />
        <Stat label="Value held in exposed holdings" value={inrc(impact.exposure)} />
        <Stat label="Estimated effect" value={inrc(impact.impact, { sign: true })} delta={pct(impact.impact_pct, 2, { sign: true }) + " of total"} deltaTone={tone(impact.impact)} />
        <div className="card">
          <div className="small muted">By asset class</div>
          {Object.entries(impact.by_asset_class as Record<string, number>).map(([k, v]) => (
            <div key={k} className="row small" style={{ justifyContent: "space-between" }}>
              <span>{ASSET_LABEL[k] || k}</span><span className={"num " + tone(v)}>{inrc(v, { sign: true })}</span>
            </div>
          ))}
          {!Object.keys(impact.by_asset_class).length && <div className="small faint">—</div>}
        </div>
      </div>
      <div className="card">
        <div className="card-head"><h2>Estimated effect by client</h2><span className="small faint">Click a client for holding-level detail</span></div>
        {impact.clients.length === 0 ? (
          <div className="empty">No client holds anything this touches.</div>
        ) : (
          <DivergingBars
            rows={impact.clients.map((c: any) => ({
              key: c.client_id, label: c.client_name, value: c.impact,
              detail: <><div className="t-title">{c.client_name}</div>{inrc(c.impact, { sign: true })} ({pct(c.impact_pct, 2, { sign: true })} of portfolio)<div>{inrc(c.exposure)} exposed</div></>,
            }))}
            onClick={(k) => setOpen(open === k ? null : (k as number))}
          />
        )}
      </div>
      {impact.clients.filter((c: any) => open == null || c.client_id === open).map((c: any) => (
        <div className="card" key={c.client_id}>
          <div className="card-head">
            <h2><Link to={`/clients/${c.client_id}`}>{c.client_name}</Link></h2>
            <span className={"num " + tone(c.impact)}>{inr(c.impact)} · {pct(c.impact_pct, 2, { sign: true })} of {inrc(c.portfolio_value)}</span>
          </div>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Holding</th><th className="num">Value</th><th className="num">Estimated effect</th><th>How</th></tr></thead>
              <tbody>
                {c.holdings.map((h: any) => (
                  <tr key={h.isin}>
                    <td>{h.name}</td>
                    <td className="num">{inr(h.value)}</td>
                    <td className={"num " + tone(h.impact)}>{inr(h.impact)}<div className="sub">{pct(h.impact_pct, 2, { sign: true })}</div></td>
                    <td className="small muted">{h.explain}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )).slice(0, open == null ? 3 : 1)}
      {open == null && impact.clients.length > 3 && <p className="small faint">Showing the three most affected clients. Click a client above for theirs.</p>}
    </div>
  );
}
