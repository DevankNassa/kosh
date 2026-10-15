import { useState } from "react";
import { api } from "../../api";
import { AllocationStack } from "../../components/Charts";
import { InstrumentSearch } from "../../components/InstrumentSearch";
import { ErrorNote } from "../../components/ui";
import { ASSET_LABEL, date, inr, inrc, pct, tone } from "../../format";

type Sell = { key: string; mode: "amount" | "units" | "all"; value: string };
type Buy = { isin: string; name: string; asset_class: string; amount: string };
type Scenario = { label: string; sells: Sell[]; buys: Buy[] };

const blank = (label: string): Scenario => ({ label, sells: [{ key: "", mode: "amount", value: "" }], buys: [] });

export default function WhatIf({ data }: { data: any }) {
  const clientId = data.client.id;
  const holdings: any[] = data.summary.holdings;
  const [scenarios, setScenarios] = useState<Scenario[]>([blank("Option A")]);
  const [results, setResults] = useState<any[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [detail, setDetail] = useState<number | null>(0);

  const hkey = (h: any) => `${h.account_id}|${h.isin}`;
  const toBody = (s: Scenario) => ({
    label: s.label,
    sells: s.sells
      .filter((x) => x.key && (x.mode === "all" || Number(x.value) > 0))
      .map((x) => {
        const [account_id, isin] = x.key.split("|");
        return {
          account_id: Number(account_id),
          isin,
          ...(x.mode === "all" ? { all: true } : x.mode === "units" ? { units: Number(x.value) } : { amount: Number(x.value) }),
        };
      }),
    buys: s.buys.filter((b) => Number(b.amount) > 0).map((b) => ({ isin: b.isin, amount: Number(b.amount) })),
  });

  const run = async () => {
    setBusy(true);
    setErr(null);
    try {
      const res = await Promise.all(scenarios.map((s) => api.post(`/api/clients/${clientId}/whatif`, toBody(s))));
      setResults(res);
      setDetail(0);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  const update = (i: number, s: Scenario) => {
    setScenarios(scenarios.map((x, j) => (j === i ? s : x)));
    setResults(null);
  };

  const exportXlsx = () =>
    api
      .download(`/api/clients/${clientId}/whatif/export`, { scenarios: scenarios.map(toBody) }, "kosh-whatif.xlsx")
      .catch((e) => setErr(e.message));

  const drift = (data.drift as any[]).filter((d) => d.target_pct != null);

  return (
    <div className="stack">
      <div className="notice info">
        Enter the changes the client is considering. Kosh works out which purchases each sale uses (first in, first out), the estimated tax, exit load and STT, and the asset mix afterwards. Compare up to three options side by side.
      </div>
      {drift.length > 0 && (
        <div className="card">
          <h3>Gap to the client's target mix</h3>
          <div className="row" style={{ gap: 18 }}>
            {drift.map((d) => (
              <span key={d.asset_class} className="small">
                {ASSET_LABEL[d.asset_class]}: {pct(d.current_pct, 0)} now, {pct(d.target_pct, 0)} target →{" "}
                <b className={tone(d.amount_to_target)}>{inrc(d.amount_to_target, { sign: true })}</b>
              </span>
            ))}
          </div>
        </div>
      )}

      <div className={"grid " + (scenarios.length > 1 ? (scenarios.length > 2 ? "g3" : "g2") : "")}>
        {scenarios.map((s, i) => (
          <ScenarioEditor
            key={i}
            s={s}
            holdings={holdings}
            hkey={hkey}
            onChange={(n) => update(i, n)}
            onRemove={scenarios.length > 1 ? () => { setScenarios(scenarios.filter((_, j) => j !== i)); setResults(null); } : undefined}
          />
        ))}
      </div>
      <div className="row no-print">
        <button className="primary" onClick={run} disabled={busy}>{busy ? "Calculating…" : results ? "Recalculate" : "Calculate"}</button>
        {scenarios.length < 3 && (
          <button onClick={() => { setScenarios([...scenarios, blank(`Option ${"ABC"[scenarios.length]}`)]); setResults(null); }}>+ Add an option to compare</button>
        )}
        <span className="spacer" />
        {results && (
          <>
            <button onClick={exportXlsx}>Export to Excel</button>
            <button onClick={() => window.print()}>Print / save PDF</button>
          </>
        )}
      </div>
      <ErrorNote error={err} />

      {results && (
        <>
          <div className="card">
            <h2>Comparison</h2>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th />
                    {results.map((_, i) => <th key={i} className="num">{scenarios[i].label}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {[
                    ["Sale value", "gross_proceeds"],
                    ["Exit loads (est.)", "exit_loads"],
                    ["STT (est.)", "stt"],
                    ["Extra tax this FY (est.)", "incremental_tax"],
                  ].map(([label, k]) => (
                    <tr key={k}>
                      <td>{label}</td>
                      {results.map((r, i) => <td key={i} className="num">{inr(r[k])}</td>)}
                    </tr>
                  ))}
                  <tr>
                    <td><b>In hand after tax and costs</b></td>
                    {results.map((r, i) => <td key={i} className="num"><b>{inr(r.net_proceeds)}</b></td>)}
                  </tr>
                  <tr>
                    <td>Tax + costs as % of sale</td>
                    {results.map((r, i) => (
                      <td key={i} className="num">
                        {r.gross_proceeds ? pct((r.incremental_tax + r.exit_loads + r.stt) / r.gross_proceeds, 2) : "—"}
                      </td>
                    ))}
                  </tr>
                  <tr>
                    <td>Total tax for {results[0].fy} after the change</td>
                    {results.map((r, i) => <td key={i} className="num">{inr(r.tax_after.total)}</td>)}
                  </tr>
                  <tr>
                    <td>Equity LTCG exemption left after</td>
                    {results.map((r, i) => <td key={i} className="num">{inr(r.tax_after.exemption_remaining)}</td>)}
                  </tr>
                  <tr>
                    <td>Asset mix after</td>
                    {results.map((r, i) => (
                      <td key={i} style={{ minWidth: 220 }}>
                        <AllocationStack rows={r.allocation_after} />
                      </td>
                    ))}
                  </tr>
                </tbody>
              </table>
            </div>
            <div className="row small faint" style={{ marginTop: 10 }}>
              Now: <span style={{ minWidth: 260, display: "inline-block" }}><AllocationStack rows={results[0].allocation_before} /></span>
            </div>
            <p className="small faint" style={{ marginTop: 8 }}>
              Assumes sale on {date(results[0].sale_date)} at prices of {date(results[0].assumptions.prices_asof)}; slab {pct(results[0].assumptions.slab_rate, 0)}, surcharge {pct(results[0].assumptions.surcharge_rate, 0)}; {results[0].assumptions.rules}. Exit loads use typical rates; check each scheme's documents.
            </p>
          </div>

          <div className="card">
            <div className="card-head">
              <h2>Purchase-by-purchase detail</h2>
              <div className="seg">
                {results.map((_, i) => (
                  <button key={i} className={detail === i ? "active" : ""} onClick={() => setDetail(i)}>{scenarios[i].label}</button>
                ))}
              </div>
            </div>
            {detail != null && results[detail] && <ScenarioDetail r={results[detail]} />}
          </div>
        </>
      )}
    </div>
  );
}

function ScenarioEditor({ s, holdings, hkey, onChange, onRemove }: {
  s: Scenario; holdings: any[]; hkey: (h: any) => string; onChange: (s: Scenario) => void; onRemove?: () => void;
}) {
  const setSell = (i: number, patch: Partial<Sell>) => onChange({ ...s, sells: s.sells.map((x, j) => (j === i ? { ...x, ...patch } : x)) });
  const byKey = Object.fromEntries(holdings.map((h) => [hkey(h), h]));
  return (
    <div className="card">
      <div className="card-head">
        <input value={s.label} onChange={(e) => onChange({ ...s, label: e.target.value })} style={{ fontWeight: 600, maxWidth: 200 }} />
        {onRemove && <button className="ghost" onClick={onRemove}>Remove</button>}
      </div>
      <h3>Sell / redeem</h3>
      {s.sells.map((x, i) => {
        const h = byKey[x.key];
        return (
          <div key={i} style={{ marginBottom: 10 }}>
            <select value={x.key} onChange={(e) => setSell(i, { key: e.target.value })} style={{ width: "100%" }}>
              <option value="">Choose a holding…</option>
              {holdings.map((h) => (
                <option key={hkey(h)} value={hkey(h)}>
                  {h.name} · {inrc(h.value)}
                </option>
              ))}
            </select>
            <div className="row" style={{ marginTop: 6 }}>
              <div className="seg">
                {(["amount", "units", "all"] as const).map((m) => (
                  <button key={m} className={x.mode === m ? "active" : ""} onClick={() => setSell(i, { mode: m })}>
                    {m === "amount" ? "₹ amount" : m === "units" ? "Units" : "All"}
                  </button>
                ))}
              </div>
              {x.mode !== "all" && (
                <input type="number" min={0} placeholder={x.mode === "amount" ? "₹" : "units"} value={x.value}
                  onChange={(e) => setSell(i, { value: e.target.value })} style={{ width: 130 }} />
              )}
              <button className="ghost" onClick={() => onChange({ ...s, sells: s.sells.filter((_, j) => j !== i) })}>✕</button>
            </div>
            {h && <div className="small faint" style={{ marginTop: 3 }}>Holding {inr(h.value)} · {h.lt_units > 0 ? "has long-term units" : "short-term only"}{h.unknown_cost_units > 0 ? " · cost missing" : ""}</div>}
          </div>
        );
      })}
      <button className="ghost" onClick={() => onChange({ ...s, sells: [...s.sells, { key: "", mode: "amount", value: "" }] })}>+ Add a sale</button>

      <h3 style={{ marginTop: 14 }}>Buy (optional, for the asset mix afterwards)</h3>
      {s.buys.map((b, i) => (
        <div key={i} className="row" style={{ marginBottom: 6 }}>
          <span className="small" style={{ flex: 1, minWidth: 140 }}>{b.name}<div className="faint">{ASSET_LABEL[b.asset_class] || b.asset_class}</div></span>
          <input type="number" placeholder="₹" value={b.amount} style={{ width: 120 }}
            onChange={(e) => onChange({ ...s, buys: s.buys.map((x, j) => (j === i ? { ...x, amount: e.target.value } : x)) })} />
          <button className="ghost" onClick={() => onChange({ ...s, buys: s.buys.filter((_, j) => j !== i) })}>✕</button>
        </div>
      ))}
      <InstrumentSearch placeholder="Add a fund or security to buy" onPick={(h) => onChange({ ...s, buys: [...s.buys, { isin: h.isin, name: h.name, asset_class: h.asset_class, amount: "" }] })} />
    </div>
  );
}

function ScenarioDetail({ r }: { r: any }) {
  return (
    <div>
      {r.warnings.map((w: string) => <div key={w} className="notice warn" style={{ marginBottom: 8 }}>{w}</div>)}
      {r.lines.length === 0 && <div className="empty">No sales in this option.</div>}
      {r.lines.map((l: any) => (
        <div key={`${l.account_id}-${l.isin}`} style={{ marginBottom: 16 }}>
          <div className="row">
            <b>{l.name}</b>
            <span className="spacer" />
            <span className="small muted">{l.units.toLocaleString("en-IN")} units × ₹{l.price.toLocaleString("en-IN")} = {inr(l.gross)}</span>
          </div>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Bought on</th><th className="num">Units</th><th className="num">Cost</th><th className="num">Sale value</th><th className="num">Gain</th><th className="num">Days held</th><th>Tax category</th><th className="num">Exit load</th></tr></thead>
              <tbody>
                {l.lots.map((x: any, i: number) => (
                  <tr key={i}>
                    <td>{date(x.acquired)}</td>
                    <td className="num">{x.units.toLocaleString("en-IN")}</td>
                    <td className="num">{x.cost != null ? inr(x.cost) : "—"}</td>
                    <td className="num">{inr(x.proceeds)}</td>
                    <td className={"num " + tone(x.gain)}>{x.gain != null ? inr(x.gain) : "—"}</td>
                    <td className="num">{x.days_held}</td>
                    <td className="small">{x.bucket_label}</td>
                    <td className="num">{inr(x.exit_load)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ))}
      <h3>Tax for the year after this option</h3>
      <table>
        <thead><tr><th>Category</th><th className="num">Before</th><th className="num">After</th><th className="num">Tax after</th></tr></thead>
        <tbody>
          {r.tax_after.buckets.filter((b: any, i: number) => b.gross || r.tax_before.buckets[i].gross).map((b: any) => {
            const before = r.tax_before.buckets.find((x: any) => x.bucket === b.bucket);
            return (
              <tr key={b.bucket}>
                <td>{b.label}</td>
                <td className="num">{inr(before?.gross)}</td>
                <td className="num">{inr(b.gross)}</td>
                <td className="num">{inr(b.tax)}</td>
              </tr>
            );
          })}
          <tr><td><b>Total incl. surcharge and cess</b></td><td className="num">{inr(r.tax_before.total)}</td><td /><td className="num"><b>{inr(r.tax_after.total)}</b></td></tr>
        </tbody>
      </table>
    </div>
  );
}
