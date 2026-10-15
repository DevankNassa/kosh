import { Fragment, useState } from "react";
import { api } from "../../api";
import { assetColor } from "../../components/Charts";
import { ErrorNote, KIND_LABEL, Modal, PriceBadge } from "../../components/ui";
import { ASSET_LABEL, date, inr, inrc, num, pct, price, tone } from "../../format";

export default function Holdings({ clientId, summary, onChanged }: { clientId: number; summary: any; onChanged: () => void }) {
  const [open, setOpen] = useState<string | null>(null);
  const [group, setGroup] = useState<"none" | "asset" | "account">("asset");
  const [costFor, setCostFor] = useState<any | null>(null);
  const [bondFor, setBondFor] = useState<any | null>(null);
  const hs: any[] = summary.holdings;
  const groups: [string, any[]][] =
    group === "none"
      ? [["All holdings", hs]]
      : Object.entries(
          hs.reduce((acc: Record<string, any[]>, h) => {
            const k = group === "asset" ? h.asset_class : h.account;
            (acc[k] = acc[k] || []).push(h);
            return acc;
          }, {}),
        );
  const key = (h: any) => `${h.account_id}-${h.isin}`;
  return (
    <div className="card">
      <div className="card-head">
        <h2>Holdings</h2>
        <div className="seg">
          {(["asset", "account", "none"] as const).map((g) => (
            <button key={g} className={group === g ? "active" : ""} onClick={() => setGroup(g)}>
              {g === "asset" ? "By asset class" : g === "account" ? "By account" : "Flat"}
            </button>
          ))}
        </div>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Instrument</th>
              <th className="num">Units</th>
              <th className="num">Price</th>
              <th className="num">Value</th>
              <th className="num">Cost</th>
              <th className="num">Unrealised</th>
              <th className="num">Day</th>
              <th>Tax status</th>
              <th className="num">XIRR</th>
            </tr>
          </thead>
          <tbody>
            {groups.map(([g, rows]) => (
              <Fragment key={g}>
                {group !== "none" && (
                  <tr className="sub-row">
                    <td colSpan={3}>
                      {group === "asset" && <i className="dot" style={{ background: assetColor(g), marginRight: 6 }} />}
                      <b>{group === "asset" ? ASSET_LABEL[g] || g : g}</b>
                    </td>
                    <td className="num"><b>{inrc(rows.reduce((s, h) => s + h.value, 0))}</b></td>
                    <td colSpan={5} />
                  </tr>
                )}
                {rows.map((h) => (
                  <Fragment key={key(h)}>
                    <tr className="clickable" onClick={() => setOpen(open === key(h) ? null : key(h))}>
                      <td style={{ maxWidth: 340 }}>
                        {h.name}
                        <div className="sub">
                          {KIND_LABEL[h.kind] || h.kind} · {h.sub_class || ""}
                          {h.rating ? ` · ${h.rating}` : ""} {group !== "account" && `· ${h.account}`}
                        </div>
                      </td>
                      <td className="num">{num(h.units, 3)}</td>
                      <td className="num">
                        {price(h.price)}
                        <div><PriceBadge level={h.price_level} source={h.price_source} /></div>
                      </td>
                      <td className="num">{inr(h.value)}</td>
                      <td className="num">{h.cost != null ? inr(h.cost) : "—"}</td>
                      <td className={"num " + tone(h.unrealised)}>
                        {h.unrealised != null ? inr(h.unrealised) : "—"}
                        <div className="sub">{pct(h.unrealised_pct, 1, { sign: true })}</div>
                      </td>
                      <td className={"num " + tone(h.day_change)}>{h.day_change != null ? inrc(h.day_change, { sign: true }) : "—"}</td>
                      <td>
                        <TaxStatus h={h} />
                      </td>
                      <td className="num">{pct(h.xirr)}</td>
                    </tr>
                    {open === key(h) && (
                      <tr>
                        <td colSpan={9} style={{ background: "var(--surface-2)" }}>
                          <LotDetail h={h} onAddCost={() => setCostFor(h)} onEditBond={() => setBondFor(h)} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
      {costFor && (
        <CostBasisModal clientId={clientId} h={costFor} onClose={() => setCostFor(null)} onDone={() => { setCostFor(null); onChanged(); }} />
      )}
      {bondFor && <BondModal h={bondFor} onClose={() => setBondFor(null)} onDone={() => { setBondFor(null); onChanged(); }} />}
    </div>
  );
}

function TaxStatus({ h }: { h: any }) {
  if (h.unknown_cost_units > 0) return <span className="badge warn">Cost missing</span>;
  const parts = [];
  if (h.lt_units > 0) parts.push(<span key="lt" className="badge good">LT {h.st_units > 0 ? pct(h.lt_units / h.units, 0) : ""}</span>);
  if (h.st_units > 0) parts.push(<span key="st" className="badge">ST {h.lt_units > 0 ? pct(h.st_units / h.units, 0) : ""}</span>);
  return (
    <div>
      <div className="row" style={{ gap: 4 }}>{parts}</div>
      {h.next_long_term_date && <div className="sub">next LT {date(h.next_long_term_date)}</div>}
    </div>
  );
}

function LotDetail({ h, onAddCost, onEditBond }: { h: any; onAddCost: () => void; onEditBond: () => void }) {
  const isBond = ["corp_bond", "gsec", "sdl", "tbill"].includes(h.kind);
  return (
    <div>
      <div className="row" style={{ marginBottom: 8 }}>
        <span className="small muted">ISIN {h.isin}{h.symbol ? ` · ${h.symbol}` : ""} · price {h.price_source} {date(h.price_date)}</span>
        {isBond && (
          <span className="small muted">
            · YTM {pct(h.ytm, 2)} · mod. duration {num(h.mod_duration, 2)} · maturity {date(h.maturity)}
          </span>
        )}
        <span className="spacer" />
        {h.unknown_cost_units > 0 && <button className="primary" onClick={onAddCost}>Add cost basis</button>}
        {isBond && <button onClick={onEditBond}>Edit bond details</button>}
      </div>
      <table>
        <thead>
          <tr>
            <th>Bought on</th><th className="num">Units</th><th className="num">Unit cost</th><th className="num">Cost</th>
            <th className="num">Value now</th><th className="num">Gain</th><th>Term</th>
          </tr>
        </thead>
        <tbody>
          {h.lots.map((l: any, i: number) => {
            const cost = l.unit_cost != null ? l.units * l.unit_cost : null;
            const val = l.units * (h.price || 0);
            return (
              <tr key={i}>
                <td>{l.date_is_estimate ? <span className="faint">unknown (statement date {date(l.acquired)})</span> : date(l.acquired)}</td>
                <td className="num">{num(l.units, 3)}</td>
                <td className="num">{l.unit_cost != null ? price(l.unit_cost) : "—"}</td>
                <td className="num">{cost != null ? inr(cost) : "—"}</td>
                <td className="num">{inr(val)}</td>
                <td className={"num " + tone(cost != null ? val - cost : 0)}>{cost != null ? inr(val - cost) : "—"}</td>
                <td>{l.term ? <span className={"badge " + (l.term === "LT" ? "good" : "")}>{l.term === "LT" ? "Long-term" : "Short-term"}</span> : <span className="badge warn">Unknown</span>}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function CostBasisModal({ clientId, h, onClose, onDone }: { clientId: number; h: any; onClose: () => void; onDone: () => void }) {
  const [lots, setLots] = useState([{ date: "", units: String(h.unknown_cost_units), price: "" }]);
  const [err, setErr] = useState<string | null>(null);
  const total = lots.reduce((s, l) => s + (Number(l.units) || 0), 0);
  const save = () =>
    api
      .post(`/api/clients/${clientId}/cost-basis`, {
        account_id: h.account_id,
        isin: h.isin,
        lots: lots.map((l) => ({ date: l.date, units: Number(l.units), price: Number(l.price) })),
      })
      .then(onDone)
      .catch((e) => setErr(e.message));
  const set = (i: number, k: string, v: string) => setLots(lots.map((l, j) => (j === i ? { ...l, [k]: v } : l)));
  return (
    <Modal
      title={`Add cost basis: ${h.name}`}
      onClose={onClose}
      footer={
        <>
          <button onClick={onClose}>Cancel</button>
          <button className="primary" onClick={save} disabled={lots.some((l) => !l.date || !l.price)}>Save</button>
        </>
      }
    >
      <p className="small muted">
        Depository statements don't include purchase cost. Enter each purchase (from the client's broker contract notes or tax P&amp;L). Units must add up to {num(h.unknown_cost_units, 4)}.
      </p>
      <table>
        <thead><tr><th>Purchase date</th><th>Units</th><th>Price per unit (₹)</th><th /></tr></thead>
        <tbody>
          {lots.map((l, i) => (
            <tr key={i}>
              <td><input type="date" value={l.date} onChange={(e) => set(i, "date", e.target.value)} /></td>
              <td><input type="number" value={l.units} onChange={(e) => set(i, "units", e.target.value)} style={{ width: 110 }} /></td>
              <td><input type="number" value={l.price} onChange={(e) => set(i, "price", e.target.value)} style={{ width: 120 }} /></td>
              <td>{lots.length > 1 && <button className="ghost" onClick={() => setLots(lots.filter((_, j) => j !== i))}>Remove</button>}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="row" style={{ marginTop: 8 }}>
        <button className="ghost" onClick={() => setLots([...lots, { date: "", units: "", price: "" }])}>+ Add another purchase</button>
        <span className="spacer" />
        <span className={"small " + (Math.abs(total - h.unknown_cost_units) > 1e-4 ? "down" : "faint")}>
          {num(total, 4)} of {num(h.unknown_cost_units, 4)} units
        </span>
      </div>
      <ErrorNote error={err} />
    </Modal>
  );
}

function BondModal({ h, onClose, onDone }: { h: any; onClose: () => void; onDone: () => void }) {
  const [f, setF] = useState({ rating: h.rating || "", maturity: h.maturity || "", coupon: "", face_value: "" });
  const [err, setErr] = useState<string | null>(null);
  const save = () => {
    const body: any = {};
    if (f.rating) body.rating = f.rating;
    if (f.maturity) body.maturity = f.maturity;
    if (f.coupon) body.coupon = Number(f.coupon) / 100;
    if (f.face_value) body.face_value = Number(f.face_value);
    api.put(`/api/instruments/${h.isin}`, body).then(onDone).catch((e) => setErr(e.message));
  };
  return (
    <Modal title={`Bond details: ${h.name}`} onClose={onClose}
      footer={<><button onClick={onClose}>Cancel</button><button className="primary" onClick={save}>Save</button></>}>
      <p className="small muted">Exchange data often lacks the exact maturity date and rating. Corrections apply to every client holding this bond.</p>
      <div className="form-grid">
        <label className="field">Credit rating<input placeholder="e.g. AAA, AA+, SOV" value={f.rating} onChange={(e) => setF({ ...f, rating: e.target.value.toUpperCase() })} /></label>
        <label className="field">Maturity date<input type="date" value={f.maturity} onChange={(e) => setF({ ...f, maturity: e.target.value })} /></label>
        <label className="field">Coupon (% a year)<input type="number" placeholder="leave blank to keep" value={f.coupon} onChange={(e) => setF({ ...f, coupon: e.target.value })} /></label>
        <label className="field">Face value (₹)<input type="number" placeholder="leave blank to keep" value={f.face_value} onChange={(e) => setF({ ...f, face_value: e.target.value })} /></label>
      </div>
      <ErrorNote error={err} />
    </Modal>
  );
}
