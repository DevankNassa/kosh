import { useEffect, useState } from "react";
import { api } from "../api";
import { date, num } from "../format";
import { ErrorNote, useApi } from "./ui";

type Coverage = { rows: number; days: number; from: string | null; to: string | null };
type MarketData = {
  prices: (Coverage & { source: string; instruments: number })[];
  indices: Coverage & { indices: number };
  actions: { rows: number; instruments: number; from: string | null; to: string | null };
  instruments: { total: number; by_kind: Record<string, number> };
  db_path: string;
  db_bytes: number | null;
  auto_refresh_after_hour: number;
  history: {
    running: boolean;
    start?: string;
    end?: string;
    done?: number;
    total?: number | null;
    source?: string | null;
    date?: string | null;
    finished?: string;
    stopped?: boolean;
    error?: string;
    sources?: Record<string, { fetched: number; rows: number; errors: number; gave_up?: boolean; last_error?: string }>;
  };
};

const SOURCE_LABEL: Record<string, string> = {
  nse: "Shares, ETFs, bonds (NSE closing prices)",
  amfi: "Mutual fund NAVs (AMFI)",
  indices: "Index closes (NSE)",
  actions: "Splits & bonus issues (NSE)",
  snapshot: "Bundled offline snapshot",
  statement: "Prices from imported statements",
  model: "Model prices (bonds)",
};

const RANGES = [
  { label: "3 months", years: 0.25 },
  { label: "1 year", years: 1 },
  { label: "2 years", years: 2 },
  { label: "3 years", years: 3 },
  { label: "5 years", years: 5 },
];

const size = (b: number | null) =>
  b == null ? "—" : b >= 1e9 ? `${(b / 1e9).toFixed(2)} GB` : `${(b / 1e6).toFixed(b >= 1e8 ? 0 : 1)} MB`;

/** What market data the database holds, loading past history, and backup. */
export function StoredData() {
  const { data, error, reload } = useApi<MarketData>("/api/market/data");
  const [years, setYears] = useState(1);
  const [err, setErr] = useState<string | null>(null);
  const h = data?.history;
  const running = !!h?.running;

  useEffect(() => {
    if (!running) return;
    const t = window.setInterval(reload, 2000);
    return () => window.clearInterval(t);
  }, [running, reload]);

  const start = () => {
    setErr(null);
    api.post("/api/market/history", { years }).then(reload).catch((e) => setErr(e.message));
  };
  const stop = () => api.post("/api/market/history/stop").then(reload);

  type Row = Coverage & { key: string; count: number };
  const rows: Row[] = [
    ...(data?.prices || []).map((p) => ({ ...p, key: p.source, count: p.instruments })),
    ...(data ? [{ ...data.indices, key: "indices", count: data.indices.indices }] : []),
  ].sort((a, b) => b.rows - a.rows);
  if (data?.actions.rows) rows.push({ ...data.actions, key: "actions", count: data.actions.instruments, days: NaN });
  const pctDone = h?.total ? Math.round(((h.done || 0) / h.total) * 100) : 0;

  return (
    <div className="card">
      <div className="card-head">
        <h2>Stored market data</h2>
        <a className="btn" href="/api/backup" download>Download database backup</a>
      </div>
      <p className="small muted">
        Every closing price and NAV Kosh fetches is saved in its SQL database (SQLite) on this computer. Nothing is
        fetched live while you work. Holdings, charts and scenarios all read from these stored prices. While Kosh is
        running it adds each day's data automatically after {data?.auto_refresh_after_hour ?? 19}:00, and fills in
        any days it missed.
      </p>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Data</th>
              <th className="num">Instruments</th>
              <th className="num">Trading days</th>
              <th>From</th>
              <th>To</th>
              <th className="num">Rows stored</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.key}>
                <td>{SOURCE_LABEL[r.key] || r.key}</td>
                <td className="num">{num(r.count, 0)}</td>
                <td className="num">{Number.isNaN(r.days) ? "—" : num(r.days, 0)}</td>
                <td className="nowrap">{date(r.from)}</td>
                <td className="nowrap">{date(r.to)}</td>
                <td className="num">{num(r.rows, 0)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="small faint" style={{ marginTop: 8 }}>
        {num(data?.instruments.total, 0)} instruments on file · database {size(data?.db_bytes ?? null)} at{" "}
        <code>{data?.db_path}</code>
      </p>

      <h3 style={{ marginTop: 18 }}>Load past history</h3>
      <p className="small muted">
        Fetches past end-of-day files from NSE and AMFI and stores them. Days already stored are skipped, so you can
        stop and resume at any time. Roughly 3–5 minutes per year of NSE data; AMFI is slower. Share prices are
        stored as actual closes; charts restate them for splits and bonus issues from NSE's corporate actions list.
      </p>
      {running ? (
        <div>
          <div className="row">
            <div className="progress" style={{ flex: 1 }} role="progressbar" aria-valuenow={pctDone} aria-valuemin={0} aria-valuemax={100}>
              <div style={{ width: `${pctDone}%` }} />
            </div>
            <span className="small nowrap">{pctDone}%</span>
            <button onClick={stop}>Stop</button>
          </div>
          <p className="small faint" style={{ marginTop: 6 }}>
            {date(h?.start)} – {date(h?.end)} · {h?.total ? `${num(h.done, 0)} of ${num(h.total, 0)} files` : "Checking what's already stored…"}
            {h?.source && ` · now: ${SOURCE_LABEL[h.source] || h.source}, ${date(h.date)}`}
          </p>
        </div>
      ) : (
        <div className="row">
          <select value={years} onChange={(e) => setYears(Number(e.target.value))}>
            {RANGES.map((r) => <option key={r.years} value={r.years}>Last {r.label}</option>)}
          </select>
          <button className="primary" onClick={start}>Load history</button>
        </div>
      )}
      {!running && h?.finished && (
        <p className="small faint" style={{ marginTop: 8 }}>
          Last load {new Date(h.finished).toLocaleString("en-IN")} ({date(h.start)} – {date(h.end)})
          {h.stopped ? ", stopped early" : ""}
          {h.error ? `, failed: ${h.error}` : ""}
          {Object.entries(h.sources || {}).map(([k, v]) => (
            <span key={k}>
              {" · "}
              {SOURCE_LABEL[k]?.split(" (")[0] || k}: {num(v.rows, 0)} prices
              {v.gave_up ? ` (stopped after errors: ${v.last_error})` : v.errors ? ` (${v.errors} files failed)` : ""}
            </span>
          ))}
        </p>
      )}
      <ErrorNote error={err || error} />
    </div>
  );
}
