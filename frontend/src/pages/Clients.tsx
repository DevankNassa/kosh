import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { ErrorNote, Loading, Modal, useApi } from "../components/ui";
import { inrc, pct, tone } from "../format";

export default function Clients() {
  const { data, error, reload } = useApi<any[]>("/api/clients");
  const nav = useNavigate();
  const [q, setQ] = useState("");
  const [adding, setAdding] = useState(false);
  if (error) return <ErrorNote error={error} />;
  if (!data) return <Loading />;
  const rows = data.filter((c) => c.name.toLowerCase().includes(q.toLowerCase()));
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Clients</h1>
          <div className="sub">{data.length} clients · {inrc(data.reduce((s, c) => s + c.value, 0))} in total</div>
        </div>
        <div className="row">
          <input placeholder="Search clients" value={q} onChange={(e) => setQ(e.target.value)} />
          <button className="primary" onClick={() => setAdding(true)}>
            Add client
          </button>
        </div>
      </div>
      <div className="card">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Client</th>
                <th>Risk profile</th>
                <th className="num">Value</th>
                <th className="num">Since previous close</th>
                <th className="num">Unrealised gain</th>
                <th className="num">XIRR</th>
                <th>Flags</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.id} className="clickable" onClick={() => nav(`/clients/${c.id}`)}>
                  <td>
                    <b style={{ fontWeight: 560 }}>{c.name}</b>
                    <div className="sub">
                      {c.holdings_count} holdings{c.family ? ` · ${c.family} family` : ""}
                    </div>
                  </td>
                  <td>{c.risk_profile || "—"}</td>
                  <td className="num">{inrc(c.value)}</td>
                  <td className={"num " + tone(c.day_change)}>
                    {inrc(c.day_change, { sign: true })}
                    <div className="sub">{pct(c.day_change_pct, 2, { sign: true })}</div>
                  </td>
                  <td className={"num " + tone(c.unrealised)}>
                    {inrc(c.unrealised, { sign: true })}
                    <div className="sub">{pct(c.unrealised_pct, 1, { sign: true })}</div>
                  </td>
                  <td className="num">{pct(c.xirr)}</td>
                  <td>
                    <div className="row" style={{ gap: 4 }}>
                      {c.is_demo && <span className="badge">Demo</span>}
                      {c.residency === "nri" && <span className="badge info">NRI</span>}
                      {c.cost_unknown_value > 0 && <span className="badge warn">Cost missing</span>}
                      {c.model_prices > 0 && <span className="badge warn">Model prices</span>}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {rows.length === 0 && <div className="empty">No clients match.</div>}
      </div>
      {adding && <AddClient onClose={() => setAdding(false)} onDone={(id) => { reload(); nav(`/clients/${id}`); }} />}
    </>
  );
}

function AddClient({ onClose, onDone }: { onClose: () => void; onDone: (id: number) => void }) {
  const [f, setF] = useState({ name: "", pan: "", slab_rate: 0.3, risk_profile: "Moderate", residency: "resident" });
  const [err, setErr] = useState<string | null>(null);
  const save = () =>
    api
      .post("/api/clients", { ...f, pan: f.pan || undefined })
      .then((c) => onDone(c.id))
      .catch((e) => setErr(e.message));
  return (
    <Modal
      title="Add client"
      onClose={onClose}
      footer={
        <>
          <button onClick={onClose}>Cancel</button>
          <button className="primary" onClick={save} disabled={!f.name}>
            Save
          </button>
        </>
      }
    >
      <p className="muted small">You can also create a client straight from a statement on the Import page.</p>
      <div className="form-grid">
        <label className="field">
          Name
          <input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} autoFocus />
        </label>
        <label className="field">
          PAN (optional)
          <input value={f.pan} maxLength={10} onChange={(e) => setF({ ...f, pan: e.target.value.toUpperCase() })} />
        </label>
        <label className="field">
          Marginal tax slab
          <select value={f.slab_rate} onChange={(e) => setF({ ...f, slab_rate: Number(e.target.value) })}>
            {[0, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3].map((r) => (
              <option key={r} value={r}>{pct(r, 0)}</option>
            ))}
          </select>
        </label>
        <label className="field">
          Residency
          <select value={f.residency} onChange={(e) => setF({ ...f, residency: e.target.value })}>
            <option value="resident">Resident</option>
            <option value="nri">NRI</option>
          </select>
        </label>
        <label className="field">
          Risk profile
          <select value={f.risk_profile} onChange={(e) => setF({ ...f, risk_profile: e.target.value })}>
            {["Conservative", "Moderate", "Moderately aggressive", "Growth", "Aggressive"].map((r) => (
              <option key={r}>{r}</option>
            ))}
          </select>
        </label>
      </div>
      <ErrorNote error={err} />
    </Modal>
  );
}
