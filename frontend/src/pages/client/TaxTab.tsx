import { ErrorNote, Loading, Stat, useApi } from "../../components/ui";
import { date, inr, inrc, pct, tone } from "../../format";

export default function TaxTab({ clientId }: { clientId: number }) {
  const { data, error } = useApi<any>(`/api/clients/${clientId}/tax`, [clientId]);
  if (error) return <ErrorNote error={error} />;
  if (!data) return <Loading label="Working out gains and tax…" />;
  const r = data.realised;
  const t = r.tax;
  const ins = data.insights;
  const a = data.assumptions;
  return (
    <div className="stack">
      <div className="notice info">
        Indicative estimates (rules for {a.rules.replace("Transfers", "transfers")}), using a {pct(a.slab_rate, 0)} marginal slab
        {a.surcharge_rate ? ` and ${pct(a.surcharge_rate, 0)} surcharge` : ""} ({a.tax_regime} regime). Change these in Profile. Confirm with a tax professional before acting.
        {a.residency === "nri" && " NRI: TDS and treaty rules are not modelled."}
      </div>
      <div className="grid g4">
        <Stat label={`Gains realised in ${r.fy}`} value={inrc(t.buckets.reduce((s: number, b: any) => s + b.gross, 0), { sign: true })} />
        <Stat label="Estimated tax on them" value={inrc(t.total)} hint={`incl. surcharge ${inrc(t.surcharge)} and cess ${inrc(t.cess)}`} />
        <Stat label="Equity LTCG exemption left" value={inrc(ins.exemption_remaining)} hint={`Unrealised long-term equity gains: ${inrc(ins.unrealised_lt_equity_gain)}`} />
        <Stat label="Losses carried forward after this year" value={inrc(t.unabsorbed_stcl + t.unabsorbed_ltcl)} hint={`Short-term ${inrc(t.unabsorbed_stcl)} · long-term ${inrc(t.unabsorbed_ltcl)}`} />
      </div>

      <div className="grid g2">
        <div className="card">
          <h2>Tax by category, {r.fy}</h2>
          <table>
            <thead>
              <tr><th>Category</th><th className="num">Net gain</th><th className="num">After set-off</th><th className="num">Taxable</th><th className="num">Tax</th></tr>
            </thead>
            <tbody>
              {t.buckets.map((b: any) => (
                <tr key={b.bucket}>
                  <td>{b.label}</td>
                  <td className={"num " + tone(b.gross)}>{inr(b.gross)}</td>
                  <td className="num">{inr(b.after_setoff)}</td>
                  <td className="num">{inr(b.taxable)}</td>
                  <td className="num">{inr(b.tax)}</td>
                </tr>
              ))}
              <tr><td>Surcharge + 4% cess</td><td colSpan={3} /><td className="num">{inr(t.surcharge + t.cess)}</td></tr>
              <tr><td><b>Total</b></td><td colSpan={3} /><td className="num"><b>{inr(t.total)}</b></td></tr>
            </tbody>
          </table>
          {t.notes.map((n: string) => <p key={n} className="small faint" style={{ marginTop: 8 }}>{n}</p>)}
        </div>

        <div className="card">
          <h2>Sales this year</h2>
          {r.rows.length === 0 ? (
            <div className="empty">No sales or redemptions in {r.fy}.</div>
          ) : (
            <div className="table-wrap" style={{ maxHeight: 360 }}>
              <table>
                <thead><tr><th>Instrument</th><th>Sold</th><th className="num">Days held</th><th className="num">Gain</th><th>Category</th></tr></thead>
                <tbody>
                  {r.rows.map((x: any, i: number) => (
                    <tr key={i}>
                      <td>{x.name}<div className="sub">bought {date(x.acquired)} · {inr(x.proceeds)} received</div></td>
                      <td className="nowrap">{date(x.sold)}</td>
                      <td className="num">{x.days_held}</td>
                      <td className={"num " + tone(x.gain)}>{x.gain != null ? inr(x.gain) : "—"}</td>
                      <td className="small">{x.bucket_label}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      <div className="grid g2">
        <div className="card">
          <h2>Turning long-term soon</h2>
          <p className="small muted">Purchases that become long-term in the next 60 days, and the approximate tax difference if a sale waited until then.</p>
          {ins.long_term_soon.length === 0 ? (
            <div className="empty">Nothing turns long-term in the next 60 days.</div>
          ) : (
            <table>
              <thead><tr><th>Instrument</th><th>Long-term on</th><th className="num">Unrealised gain</th><th className="num">Tax difference</th></tr></thead>
              <tbody>
                {ins.long_term_soon.map((x: any, i: number) => (
                  <tr key={i}>
                    <td>{x.name}<div className="sub">bought {date(x.acquired)}</div></td>
                    <td className="nowrap">{date(x.long_term_on)}<div className="sub">in {x.days_left} days</div></td>
                    <td className="num">{inr(x.unrealised_gain)}</td>
                    <td className="num">{inr(x.approx_tax_difference)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        <div className="card">
          <h2>Holdings below cost</h2>
          <p className="small muted">Unrealised losses. If realised, these could be set off against gains under the usual rules.</p>
          {ins.unrealised_losses.length === 0 ? (
            <div className="empty">No holdings below cost.</div>
          ) : (
            <table>
              <thead><tr><th>Instrument</th><th className="num">Short-term</th><th className="num">Long-term</th></tr></thead>
              <tbody>
                {ins.unrealised_losses.map((x: any, i: number) => (
                  <tr key={i}>
                    <td>{x.name}<div className="sub">{x.lots} purchase{x.lots > 1 ? "s" : ""}</div></td>
                    <td className="num down">{x.st_loss ? inr(x.st_loss) : "—"}</td>
                    <td className="num down">{x.lt_loss ? inr(x.lt_loss) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      <div className="card">
        <h2>Cost of selling ₹1 lakh from each holding today</h2>
        <p className="small muted">Estimated extra tax, exit load and STT if ₹1 lakh (or the whole holding, if smaller) were sold today, given this year's other gains. For comparison only.</p>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Holding</th><th className="num">Amount</th><th className="num">Tax + costs</th><th className="num">Per ₹1 lakh</th></tr></thead>
            <tbody>
              {[...data.tax_per_lakh].sort((x: any, y: any) => (x.per_lakh ?? 0) - (y.per_lakh ?? 0)).map((x: any) => (
                <tr key={`${x.account_id}-${x.isin}`}>
                  <td>{x.name}{x.has_unknown_cost && <> <span className="badge warn">cost missing</span></>}</td>
                  <td className="num">{inr(x.amount)}</td>
                  <td className="num">{inr(x.tax_and_costs)}</td>
                  <td className="num">{inr(x.per_lakh)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
