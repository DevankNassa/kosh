import { useEffect, useState } from "react";
import { useStatus } from "../App";
import { api } from "../api";
import { LineChart } from "../components/Charts";
import { ErrorNote, useApi } from "../components/ui";
import { date, num, pct } from "../format";

export default function Settings() {
  const { status, reload } = useStatus();
  const [f, setF] = useState({ distributor_name: "", arn: "", firm_name: "" });
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const audit = useApi<any[]>("/api/audit?limit=30");
  useEffect(() => {
    if (status) setF(status.settings);
  }, [status]);
  if (!status) return null;
  const m = status.market || {};
  const curve = status.yield_curve;

  const save = () =>
    api.put("/api/settings", f).then(() => { setMsg("Saved"); reload(); }).catch((e) => setErr(e.message));
  const act = (name: string, url: string, confirmText?: string) => {
    if (confirmText && !window.confirm(confirmText)) return;
    setBusy(name);
    setErr(null);
    api.post(url).then(() => { reload(); audit.reload(); setMsg(`${name}: done`); }).catch((e) => setErr(e.message)).finally(() => setBusy(null));
  };

  const src = (k: string, label: string, detail: (x: any) => string) => {
    const x = m[k];
    return (
      <tr key={k}>
        <td>{label}</td>
        <td>{x ? (x.ok ? <span className="badge good">OK</span> : <span className="badge bad">Failed</span>) : <span className="badge">Not run</span>}</td>
        <td className="small">{x ? (x.ok ? detail(x) : x.error) : "—"}</td>
      </tr>
    );
  };

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Settings &amp; data</h1>
          <div className="sub">Your details, market data, and demo data.</div>
        </div>
      </div>
      <div className="grid g2">
        <div className="card">
          <h2>Distributor details</h2>
          <p className="small muted">Shown on every screen and export, with the standard mutual fund disclaimer.</p>
          <div className="form-grid">
            <label className="field">Your name<input value={f.distributor_name} onChange={(e) => setF({ ...f, distributor_name: e.target.value })} /></label>
            <label className="field">ARN<input value={f.arn} onChange={(e) => setF({ ...f, arn: e.target.value })} /></label>
            <label className="field">Firm name (optional)<input value={f.firm_name} onChange={(e) => setF({ ...f, firm_name: e.target.value })} /></label>
          </div>
          <div className="row" style={{ marginTop: 12 }}>
            <button className="primary" onClick={save}>Save</button>
            {msg && <span className="small up">{msg}</span>}
          </div>
        </div>

        <div className="card">
          <div className="card-head">
            <h2>Market data</h2>
            <button onClick={() => act("Market data refresh", "/api/market/refresh")} disabled={!!busy}>
              {busy === "Market data refresh" ? "Fetching (about 30s)…" : "Refresh now"}
            </button>
          </div>
          <table>
            <tbody>
              {src("amfi", "Mutual fund NAVs (AMFI)", (x) => `${num(x.schemes, 0)} schemes, NAV date ${date(x.asof)}`)}
              {src("nse", "Shares, ETFs, bonds (NSE)", (x) => `${num(x.securities, 0)} securities, ${date(x.asof)}`)}
              {src("sectors", "Sectors (NSE index lists)", (x) => `${num(x.count, 0)} companies`)}
              {src("indices", "Index levels (NSE)", (x) => `${x.count} indices`)}
              {m.snapshot && src("snapshot", "Bundled offline snapshot", (x) => `used, prices of ${date(x.asof)}`)}
            </tbody>
          </table>
          <p className="small faint" style={{ marginTop: 8 }}>Last refresh {m.finished ? new Date(m.finished).toLocaleString("en-IN") : "never"}. End-of-day data; refresh once a day after the market closes.</p>
        </div>
      </div>

      <div className="grid g2" style={{ marginTop: 16 }}>
        <div className="card">
          <h2>Government bond yield curve</h2>
          <p className="small muted">{curve?.source} {curve?.asof ? `· ${date(curve.asof)}` : ""}. Used to price bonds with no recent trade and for rate scenarios.</p>
          {curve && <LineChart points={curve.points} xLabel="Years to maturity" yFormat={(v) => pct(v, 2)} xFormat={(v) => `${v}y`} />}
        </div>
        <div className="card">
          <h2>Demo data</h2>
          <p className="small muted">
            {status.demo_clients} fictional demo clients holding real instruments at today's prices, plus sample "what if" events. Remove them before adding real clients, or reset to start the demo fresh.
          </p>
          <div className="row">
            <button onClick={() => act("Demo reset", "/api/demo/reset", "Reset the demo clients and sample events to their original state?")} disabled={!!busy}>Reset demo</button>
            <button className="danger" onClick={() => act("Demo removal", "/api/demo/remove", "Remove all demo clients and sample events?")} disabled={!!busy}>Remove demo data</button>
          </div>
          <h3 style={{ marginTop: 18 }}>Activity log</h3>
          <div className="table-wrap" style={{ maxHeight: 240 }}>
            <table>
              <tbody>
                {(audit.data || []).map((a, i) => (
                  <tr key={i}>
                    <td className="small nowrap">{new Date(a.ts + "Z").toLocaleString("en-IN")}</td>
                    <td className="small">{a.action.replace(/_/g, " ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
      <ErrorNote error={err} />
    </>
  );
}
