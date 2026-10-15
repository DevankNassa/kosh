import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { AllocationStack, assetColor, BarList, sortAssets } from "../components/Charts";
import { ErrorNote, Loading, Stat, Tabs, useApi } from "../components/ui";
import { ASSET_LABEL, date, inr, inrc, num, pct, price, tone } from "../format";
import Holdings from "./client/Holdings";
import TaxTab from "./client/TaxTab";
import WhatIf from "./client/WhatIf";

type Tab = "overview" | "holdings" | "tax" | "whatif" | "txns" | "profile";

export default function ClientDetail() {
  const { id } = useParams();
  const { data, error, reload } = useApi<any>(`/api/clients/${id}`, [id]);
  const [tab, setTab] = useState<Tab>("overview");
  if (error) return <ErrorNote error={error} />;
  if (!data) return <Loading />;
  const c = data.client;
  const s = data.summary;
  return (
    <>
      <div className="page-head">
        <div>
          <div className="small"><Link to="/clients">← Clients</Link></div>
          <h1 style={{ marginTop: 4 }}>
            {c.name}{" "}
            {c.is_demo && <span className="badge">Demo client</span>}{" "}
            {c.residency === "nri" && <span className="badge info">NRI</span>}
          </h1>
          <div className="sub">
            {c.risk_profile || "Risk profile not set"} · {c.tax_regime === "old" ? "Old" : "New"} tax regime · slab {pct(c.slab_rate, 0)}
            {c.pan_masked ? ` · PAN ${c.pan_masked}` : ""} · prices as of {date(s.asof)}
          </div>
        </div>
        <div className="row no-print">
          <button onClick={() => setTab("whatif")} className="primary">Plan a change</button>
          <button onClick={() => window.print()}>Print</button>
        </div>
      </div>

      <Tabs<Tab>
        value={tab}
        onChange={setTab}
        tabs={[
          { id: "overview", label: "Overview" },
          { id: "holdings", label: `Holdings (${s.holdings_count})` },
          { id: "tax", label: "Tax" },
          { id: "whatif", label: "What-if planner" },
          { id: "txns", label: "Transactions" },
          { id: "profile", label: "Profile" },
        ]}
      />

      {tab === "overview" && <Overview data={data} />}
      {tab === "holdings" && <Holdings clientId={c.id} summary={s} onChanged={reload} />}
      {tab === "tax" && <TaxTab clientId={c.id} />}
      {tab === "whatif" && <WhatIf data={data} />}
      {tab === "txns" && <Transactions clientId={c.id} />}
      {tab === "profile" && <Profile client={c} accounts={data.accounts} onSaved={reload} />}
    </>
  );
}

function Overview({ data }: { data: any }) {
  const s = data.summary;
  const al = data.allocations;
  const drift = data.drift as any[];
  const debt = data.debt;
  const targets: Record<string, number | null> = Object.fromEntries(drift.map((d) => [d.asset_class, d.target_pct]));
  const classRows = sortAssets(
    drift.map((d) => ({ name: d.asset_class, value: d.current_value, pct: d.current_pct })),
  ).map((r) => ({ ...r, label: ASSET_LABEL[r.name] || r.name }));
  return (
    <div className="stack">
      {(s.cost_unknown_value > 0 || s.model_prices > 0 || data.client.residency === "nri" || s.warnings.length > 0) && (
        <div>
          {data.client.residency === "nri" && (
            <div className="notice info">NRI client: tax is deducted at source on redemptions and treaty rules may apply. Kosh shows resident-rate estimates only.</div>
          )}
          {s.cost_unknown_value > 0 && (
            <div className="notice warn">
              {inrc(s.cost_unknown_value)} of holdings have no purchase cost yet (from a depository statement). They are valued, but left out of gains and tax until the cost is added in Holdings.
            </div>
          )}
          {s.model_prices > 0 && (
            <div className="notice warn">{s.model_prices} bond holding(s) had no recent trade and are priced from the yield curve plus a rating spread.</div>
          )}
          {s.warnings.map((w: string) => <div key={w} className="notice warn">{w}</div>)}
        </div>
      )}
      <div className="grid g4">
        <Stat label="Current value" value={inrc(s.value)} hero />
        <Stat
          label="Since previous close"
          value={inrc(s.day_change, { sign: true })}
          delta={pct(s.day_change_pct, 2, { sign: true })}
          deltaTone={tone(s.day_change)}
        />
        <Stat
          label="Unrealised gain"
          value={inrc(s.unrealised, { sign: true })}
          delta={`${pct(s.unrealised_pct, 1, { sign: true })} on cost of ${inrc(s.cost)}`}
          deltaTone={tone(s.unrealised)}
        />
        <Stat label="XIRR (annualised)" value={pct(s.xirr)} hint="Holdings with full cost history" />
      </div>

      <div className="grid g2">
        <div className="card">
          <div className="card-head">
            <h2>Asset mix vs target</h2>
            <span className="small faint">▍ = client's chosen target</span>
          </div>
          <AllocationStack rows={al.asset_class} />
          <div style={{ marginTop: 14 }}>
            <BarList rows={classRows} color={assetColor} targets={targets} />
          </div>
          <div className="table-wrap" style={{ marginTop: 10 }}>
            <table>
              <thead>
                <tr><th>Asset class</th><th className="num">Now</th><th className="num">Target</th><th className="num">To reach target</th></tr>
              </thead>
              <tbody>
                {drift.map((d) => (
                  <tr key={d.asset_class}>
                    <td><i className="dot" style={{ background: assetColor(d.asset_class), marginRight: 6 }} />{ASSET_LABEL[d.asset_class]}</td>
                    <td className="num">{pct(d.current_pct)}</td>
                    <td className="num">{d.target_pct != null ? pct(d.target_pct, 0) : "—"}</td>
                    <td className={"num " + tone(d.amount_to_target)}>
                      {d.amount_to_target != null ? inrc(d.amount_to_target, { sign: true }) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
        <div className="card">
          <h2>By category</h2>
          <BarList rows={al.sub_class.slice(0, 9)} color={() => "var(--s-equity)"} labelWidth={170} />
          {al.sector.length > 0 && (
            <>
              <h3 style={{ marginTop: 16 }}>Direct shares by sector</h3>
              <BarList rows={al.sector} color={() => "var(--s-equity)"} labelWidth={170} />
            </>
          )}
        </div>
      </div>

      <div className="grid g2">
        <div className="card">
          <h2>Largest issuers and fund houses</h2>
          <BarList rows={al.issuer.slice(0, 8)} color={() => "var(--s-equity)"} labelWidth={190} />
          <p className="small faint" style={{ marginTop: 8 }}>
            A company's shares and bonds count together. Mutual funds are shown by fund house; their underlying holdings are not yet looked through.
          </p>
        </div>
        <div className="card">
          <h2>Debt</h2>
          {debt.debt_value > 0 ? (
            <>
              <div className="grid g3" style={{ gap: 10 }}>
                <div><div className="small muted">Debt exposure</div><b>{inrc(debt.debt_value)}</b></div>
                <div><div className="small muted">Weighted duration</div><b>{debt.weighted_mod_duration != null ? `${num(debt.weighted_mod_duration, 1)} yrs` : "—"}</b></div>
                <div><div className="small muted">Bond yield (YTM)</div><b>{debt.bond_weighted_ytm != null ? pct(debt.bond_weighted_ytm, 2) : "—"}</b></div>
              </div>
              <p className="small faint" style={{ marginTop: 6 }}>
                A 1% rise in yields would lower debt values by about {debt.weighted_mod_duration != null ? inrc(debt.debt_value * debt.weighted_mod_duration / 100) : "—"}. {debt.duration_note}
              </p>
              {al.rating.length > 0 && (
                <>
                  <h3 style={{ marginTop: 12 }}>Credit quality</h3>
                  <BarList rows={al.rating} color={() => "var(--s-debt)"} labelWidth={170} />
                </>
              )}
              {debt.cash_flows_12m.length > 0 && (
                <>
                  <h3 style={{ marginTop: 12 }}>Coupons and maturities, next 12 months</h3>
                  <table>
                    <tbody>
                      {debt.cash_flows_12m.map((f: any, i: number) => (
                        <tr key={i}>
                          <td className="nowrap">{date(f.date)}</td>
                          <td>{f.name}<div className="sub">{f.type === "maturity" ? "Maturity (principal)" : "Coupon"}</div></td>
                          <td className="num">{inr(f.amount)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <p className="small faint">Dates are estimated where the exchange lists only the maturity year.</p>
                </>
              )}
            </>
          ) : (
            <div className="empty">No debt holdings.</div>
          )}
        </div>
      </div>
    </div>
  );
}

function Transactions({ clientId }: { clientId: number }) {
  const { data } = useApi<any[]>(`/api/clients/${clientId}/transactions`, [clientId]);
  const [q, setQ] = useState("");
  if (!data) return <Loading />;
  const rows = data.filter((t) => t.name.toLowerCase().includes(q.toLowerCase()));
  return (
    <div className="card">
      <div className="card-head">
        <h2>Transactions</h2>
        <input placeholder="Filter by instrument" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      <div className="table-wrap" style={{ maxHeight: 640 }}>
        <table>
          <thead>
            <tr>
              <th>Date</th><th>Type</th><th>Instrument</th><th>Account</th>
              <th className="num">Units</th><th className="num">Price</th><th className="num">Amount</th><th>Source</th>
            </tr>
          </thead>
          <tbody>
            {rows.slice(0, 500).map((t) => (
              <tr key={t.id}>
                <td className="nowrap">{date(t.date)}{t.date_is_estimate && <div className="sub">date estimated</div>}</td>
                <td>{t.type === "OPENING" ? <span className="badge warn">Opening</span> : t.type === "SELL" ? <span className="badge">Sell</span> : <span className="badge info">Buy</span>}</td>
                <td>{t.name}</td>
                <td className="small muted">{t.account}</td>
                <td className="num">{num(t.units, 3)}</td>
                <td className="num">{t.price != null ? price(t.price) : <span className="faint">unknown</span>}</td>
                <td className="num">{t.amount != null ? inr(t.amount) : "—"}</td>
                <td className="small muted">{t.source}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length > 500 && <p className="small faint">Showing the latest 500 of {rows.length}.</p>}
    </div>
  );
}

function Profile({ client, accounts, onSaved }: { client: any; accounts: any[]; onSaved: () => void }) {
  const nav = useNavigate();
  const [f, setF] = useState({ ...client, target_allocation: { equity: 0, debt: 0, hybrid: 0, gold: 0, ...(client.target_allocation || {}) } });
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const ta = f.target_allocation as Record<string, number>;
  const taTotal = Object.values(ta).reduce((a, b) => a + (Number(b) || 0), 0);
  const save = () => {
    setErr(null);
    const body: any = {
      name: f.name, email: f.email || null, residency: f.residency, tax_regime: f.tax_regime,
      slab_rate: Number(f.slab_rate), surcharge_rate: Number(f.surcharge_rate), risk_profile: f.risk_profile,
      family: f.family || null, notes: f.notes || null, cf_stcl: Number(f.cf_stcl) || 0, cf_ltcl: Number(f.cf_ltcl) || 0,
      target_allocation: Object.fromEntries(Object.entries(ta).filter(([, v]) => Number(v) > 0).map(([k, v]) => [k, Number(v)])),
    };
    api.put(`/api/clients/${client.id}`, body).then(() => { setMsg("Saved"); onSaved(); }).catch((e) => setErr(e.message));
  };
  const remove = () => {
    if (!window.confirm(`Delete ${client.name} and all their holdings from Kosh? This cannot be undone.`)) return;
    api.del(`/api/clients/${client.id}`).then(() => nav("/clients"));
  };
  return (
    <div className="stack">
      <div className="card">
        <h2>Client profile</h2>
        <div className="form-grid">
          <label className="field">Name<input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></label>
          <label className="field">Email<input value={f.email || ""} onChange={(e) => setF({ ...f, email: e.target.value })} /></label>
          <label className="field">Family / household<input value={f.family || ""} onChange={(e) => setF({ ...f, family: e.target.value })} /></label>
          <label className="field">Risk profile
            <select value={f.risk_profile || ""} onChange={(e) => setF({ ...f, risk_profile: e.target.value })}>
              {["", "Conservative", "Moderate", "Moderately aggressive", "Growth", "Aggressive"].map((r) => <option key={r} value={r}>{r || "Not set"}</option>)}
            </select>
          </label>
          <label className="field">Residency
            <select value={f.residency} onChange={(e) => setF({ ...f, residency: e.target.value })}>
              <option value="resident">Resident</option><option value="nri">NRI</option>
            </select>
          </label>
          <label className="field">Tax regime
            <select value={f.tax_regime} onChange={(e) => setF({ ...f, tax_regime: e.target.value })}>
              <option value="new">New</option><option value="old">Old</option>
            </select>
          </label>
          <label className="field">Marginal slab rate
            <select value={f.slab_rate} onChange={(e) => setF({ ...f, slab_rate: e.target.value })}>
              {[0, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3].map((r) => <option key={r} value={r}>{pct(r, 0)}</option>)}
            </select>
          </label>
          <label className="field">Surcharge
            <select value={f.surcharge_rate} onChange={(e) => setF({ ...f, surcharge_rate: e.target.value })}>
              {[0, 0.1, 0.15, 0.25, 0.37].map((r) => <option key={r} value={r}>{pct(r, 0)}</option>)}
            </select>
          </label>
          <label className="field">Carried-forward short-term loss (₹)<input type="number" value={f.cf_stcl} onChange={(e) => setF({ ...f, cf_stcl: e.target.value })} /></label>
          <label className="field">Carried-forward long-term loss (₹)<input type="number" value={f.cf_ltcl} onChange={(e) => setF({ ...f, cf_ltcl: e.target.value })} /></label>
        </div>
        <h3 style={{ marginTop: 18 }}>Target asset mix chosen by the client</h3>
        <div className="form-grid">
          {["equity", "debt", "hybrid", "gold"].map((k) => (
            <label className="field" key={k}>{ASSET_LABEL[k]} (%)
              <input type="number" min={0} max={100} value={Math.round((ta[k] || 0) * 100)}
                onChange={(e) => setF({ ...f, target_allocation: { ...ta, [k]: Number(e.target.value) / 100 } })} />
            </label>
          ))}
        </div>
        <p className={"small " + (Math.abs(taTotal - 1) > 0.01 && taTotal > 0 ? "down" : "faint")}>Total {pct(taTotal, 0)} (must be 100%)</p>
        <label className="field" style={{ marginTop: 10 }}>Notes<textarea rows={3} value={f.notes || ""} onChange={(e) => setF({ ...f, notes: e.target.value })} /></label>
        <div className="row" style={{ marginTop: 14 }}>
          <button className="primary" onClick={save}>Save profile</button>
          {msg && <span className="up small">{msg}</span>}
          <span className="spacer" />
          <button className="danger" onClick={remove}>Delete client</button>
        </div>
        <ErrorNote error={err} />
      </div>
      <div className="card">
        <h2>Accounts</h2>
        <table>
          <thead><tr><th>Type</th><th>Provider</th><th>Folio / account</th><th>Distributor code</th></tr></thead>
          <tbody>
            {accounts.map((a) => (
              <tr key={a.id}>
                <td>{a.kind === "demat" ? "Demat" : "MF folio"}</td>
                <td>{a.provider}</td>
                <td>{a.identifier}</td>
                <td>{a.arn || <span className="faint">—</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
