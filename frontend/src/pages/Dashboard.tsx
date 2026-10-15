import { Link, useNavigate } from "react-router-dom";
import { AllocationStack, DivergingBars } from "../components/Charts";
import { ErrorNote, Loading, Stat, useApi } from "../components/ui";
import { ASSET_LABEL, date, inrc, pct, tone } from "../format";

export const EVENT_KIND: Record<string, string> = {
  rate: "Rates",
  rating: "Credit",
  corporate: "Company",
  sector: "Sector",
  market: "Market",
};

export default function Dashboard() {
  const { data, error, loading } = useApi<any>("/api/dashboard");
  const nav = useNavigate();
  if (error) return <ErrorNote error={error} />;
  if (!data || loading) return <Loading label="Valuing every client portfolio…" />;
  const a = data.alerts;
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Morning review</h1>
          <div className="sub">
            What moved your clients' portfolios at the last market close ({date(data.asof)}), and what's in the news inbox.
          </div>
        </div>
      </div>

      <div className="grid g4" style={{ marginBottom: 16 }}>
        <Stat label="Total value across clients" value={inrc(data.book_value)} hero />
        <Stat
          label="Change since previous close"
          value={inrc(data.day_change, { sign: true })}
          delta={pct(data.day_change_pct, 2, { sign: true })}
          deltaTone={tone(data.day_change)}
        />
        <Stat label="Clients" value={data.clients.length} hint={<AllocationStack rows={data.allocation} />} />
        <div className="card">
          <div className="small muted" style={{ marginBottom: 6 }}>Needs attention</div>
          <div className="stack" style={{ gap: 6, fontSize: 13 }}>
            <span>
              <span className="badge info">{a.long_term_soon}</span> lots turn long-term within 60 days
            </span>
            <span>
              <span className="badge warn">{a.drift_clients}</span> clients 5%+ away from target mix
            </span>
            <span>
              <span className="badge warn">{a.cost_unknown_clients}</span> clients with holdings missing cost
            </span>
            {a.stale_prices > 0 && (
              <span>
                <span className="badge bad">{a.stale_prices}</span> holdings with stale prices
              </span>
            )}
          </div>
        </div>
      </div>

      <div className="grid g-main">
        <div className="stack">
          <div className="card">
            <div className="card-head">
              <h2>Client moves since previous close</h2>
              <span className="small faint">Click a client to open</span>
            </div>
            <DivergingBars
              rows={data.clients.map((c: any) => ({
                key: c.client_id,
                label: c.name,
                value: c.day_change,
                detail: (
                  <>
                    <div className="t-title">{c.name}</div>
                    <div>
                      {inrc(c.day_change, { sign: true })} ({pct(c.day_change_pct, 2, { sign: true })}) on {inrc(c.value)}
                    </div>
                    {c.top_contributors.map((t: any) => (
                      <div key={t.name} className="small">
                        {t.symbol || t.name.slice(0, 32)}: {inrc(t.day_change, { sign: true })}
                      </div>
                    ))}
                  </>
                ),
              }))}
              onClick={(id) => nav(`/clients/${id}`)}
            />
          </div>

          <div className="card">
            <div className="card-head">
              <h2>Biggest movers in client holdings</h2>
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Instrument</th>
                    <th className="num">Price change</th>
                    <th className="num">Clients</th>
                    <th className="num">Held value</th>
                    <th className="num">Effect on clients</th>
                  </tr>
                </thead>
                <tbody>
                  {data.top_movers.map((m: any) => (
                    <tr key={m.isin}>
                      <td>
                        {m.name}
                        <div className="sub">{m.symbol || m.isin}</div>
                      </td>
                      <td className={"num " + tone(m.price_change_pct)}>{pct(m.price_change_pct, 2, { sign: true })}</td>
                      <td className="num">{m.clients}</td>
                      <td className="num">{inrc(m.value)}</td>
                      <td className={"num " + tone(m.day_change)}>{inrc(m.day_change, { sign: true })}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        <div className="stack">
          <div className="card">
            <div className="card-head">
              <h2>Events inbox</h2>
              <Link to="/events">All events →</Link>
            </div>
            {data.events.length === 0 && <div className="empty">No events yet.</div>}
            {data.events.map((e: any) => (
              <Link
                key={e.id}
                to={`/events/${e.id}`}
                style={{ display: "block", color: "inherit", textDecoration: "none", padding: "10px 0", borderTop: "1px solid var(--grid)" }}
              >
                <div className="row" style={{ gap: 6 }}>
                  <span className="badge">{EVENT_KIND[e.kind] || e.kind}</span>
                  {e.is_sample && <span className="badge info">Sample · hypothetical</span>}
                  <span className="spacer" />
                  <span className="small faint">{date(e.date)}</span>
                </div>
                <div style={{ fontWeight: 560, margin: "4px 0 2px" }}>{e.title}</div>
                <div className="small muted">
                  {e.clients_exposed} {e.clients_exposed === 1 ? "client" : "clients"} exposed · {inrc(e.exposure)} held ·{" "}
                  <span className={tone(e.impact)}>estimated {inrc(e.impact, { sign: true })}</span>
                </div>
              </Link>
            ))}
          </div>

          <div className="card">
            <h2>Clients who need a look</h2>
            {data.clients
              .filter((c: any) => c.drift.length || c.cost_unknown_value > 0 || c.long_term_soon)
              .slice(0, 8)
              .map((c: any) => (
                <div key={c.client_id} style={{ padding: "8px 0", borderTop: "1px solid var(--grid)" }}>
                  <Link to={`/clients/${c.client_id}`} style={{ fontWeight: 560 }}>
                    {c.name}
                  </Link>
                  <div className="small muted">
                    {c.drift.map((d: any) => (
                      <div key={d.asset_class}>
                        {ASSET_LABEL[d.asset_class]} {pct(d.current_pct, 0)} vs target {pct(d.target_pct, 0)}
                      </div>
                    ))}
                    {c.cost_unknown_value > 0 && <div>{inrc(c.cost_unknown_value)} of holdings without cost basis</div>}
                    {c.long_term_soon > 0 && <div>{c.long_term_soon} lots turn long-term within 60 days</div>}
                  </div>
                </div>
              ))}
          </div>
        </div>
      </div>
    </>
  );
}
