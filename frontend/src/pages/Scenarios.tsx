import { useEffect, useState } from "react";
import { api } from "../api";
import { describeShock, ImpactView, Shock, ShockBuilder } from "../components/Impact";
import { ErrorNote, Loading } from "../components/ui";

const PRESETS: { label: string; shock: Shock }[] = [
  { label: "Rates −25 bps", shock: { yield_shift_bps: -25 } },
  { label: "Rates +50 bps", shock: { yield_shift_bps: 50 } },
  { label: "Nifty −10%", shock: { equity_move_pct: -10 } },
  { label: "Nifty −20%, rates −50 bps", shock: { equity_move_pct: -20, yield_shift_bps: -50 } },
  { label: "Credit stress (AA and below +150 bps)", shock: { spread_bps: 150, rating_buckets: ["AA", "A", "BBB", "Below BBB", "Unrated / unknown"] } },
  { label: "Gold +10%", shock: { gold_move_pct: 10 } },
];

export default function Scenarios() {
  const [shock, setShock] = useState<Shock>(PRESETS[2].shock);
  const [impact, setImpact] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const t = window.setTimeout(() => {
      setBusy(true);
      api.post("/api/scenario", shock).then(setImpact).catch((e) => setErr(e.message)).finally(() => setBusy(false));
    }, 350);
    return () => window.clearTimeout(t);
  }, [JSON.stringify(shock)]);
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Scenarios</h1>
          <div className="sub">Stress every client portfolio at once. Results update as you change the inputs.</div>
        </div>
      </div>
      <div className="card">
        <div className="row" style={{ marginBottom: 12 }}>
          {PRESETS.map((p) => (
            <button key={p.label} onClick={() => setShock(p.shock)}>{p.label}</button>
          ))}
        </div>
        <ShockBuilder value={shock} onChange={setShock} />
        <div className="small muted" style={{ marginTop: 8 }}>
          Scenario: <b>{describeShock(shock)}</b> {busy && <span className="spinner" style={{ verticalAlign: "middle", marginLeft: 6 }} />}
        </div>
      </div>
      <ErrorNote error={err} />
      <div style={{ marginTop: 16 }}>{impact ? <ImpactView impact={impact} /> : <Loading />}</div>
    </>
  );
}
