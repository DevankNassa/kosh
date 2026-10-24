import { useEffect, useState } from "react";
import { api } from "../api";
import { MultiLineChart } from "../components/Charts";
import { InstrumentHit, InstrumentSearch } from "../components/InstrumentSearch";
import { BusyOverlay, ErrorNote, KIND_LABEL, Loading, useApi } from "../components/ui";
import { date, pct, price } from "../format";
import { EVENT_KIND } from "./Dashboard";

type ChartSeries = { date: string; value: number }[];
type ChartResponse = {
  event: { id: number; title: string; date: string } | null;
  sector: string | null;
  sector_index: string | null;
  market_index: string;
  start: string;
  end: string;
  series: Record<string, ChartSeries>;
};

type PriceHistory = {
  isin: string;
  name: string;
  symbol: string | null;
  kind: string;
  adjusted: boolean;
  actions: [string, number][];
  points: { date: string; price: number; close: number; source: string }[];
};

const actionLabel = (f: number) =>
  f < 1 ? `prices before it × ${+f.toFixed(4)}` : `consolidation, prices before it × ${+f.toFixed(2)}`;

const PERIODS = [
  { label: "1M", days: 31 },
  { label: "6M", days: 183 },
  { label: "1Y", days: 365 },
  { label: "3Y", days: 1096 },
  { label: "All", days: 36500 },
];

// Categorical series slots, in fixed order. A slot sticks to its instrument, so
// removing one never repaints the others.
const SERIES_COLORS = ["var(--s-equity)", "var(--s-debt)", "var(--s-hybrid)", "var(--s-gold)", "var(--s-other)"];
const MAX_SERIES = SERIES_COLORS.length;

type Picked = InstrumentHit & { slot: number };

/** Daily closing prices / NAVs stored in the database, for one or several instruments. */
function PriceHistoryCard() {
  const [picks, setPicks] = useState<Picked[]>([]);
  const [days, setDays] = useState(365);
  const [mode, setMode] = useState<"price" | "change">("price");
  const [hist, setHist] = useState<Record<string, PriceHistory>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const key = (isin: string) => `${isin}:${days}`;

  useEffect(() => {
    const missing = picks.filter((p) => !hist[key(p.isin)]);
    if (!missing.length) return;
    let live = true;
    setLoading(true);
    setError(null);
    Promise.all(missing.map((p) => api.get<PriceHistory>(`/api/instruments/${p.isin}/prices?days=${days}`)))
      .then((rows) => live && setHist((h) => ({ ...h, ...Object.fromEntries(rows.map((r, i) => [key(missing[i].isin), r])) })))
      .catch((e) => live && setError(String(e.message || e)))
      .finally(() => live && setLoading(false));
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [picks, days]);

  const add = (i: InstrumentHit) => {
    if (picks.some((p) => p.isin === i.isin) || picks.length >= MAX_SERIES) return;
    const used = new Set(picks.map((p) => p.slot));
    const slot = SERIES_COLORS.findIndex((_, n) => !used.has(n));
    if (picks.length === 1 && mode === "price") setMode("change"); // different price scales: compare % change
    setPicks([...picks, { ...i, slot }]);
  };
  const remove = (isin: string) => {
    const rest = picks.filter((p) => p.isin !== isin);
    if (rest.length <= 1) setMode("price");
    setPicks(rest);
  };

  const rows = picks.map((p) => {
    const h = hist[key(p.isin)];
    const pts = h?.points || [];
    const first = pts[0];
    const last = pts[pts.length - 1];
    return { pick: p, h, pts, first, last, change: first && last ? last.price / first.price - 1 : null };
  });
  const shown = rows.filter((r) => r.pts.length > 1);
  const label = (p: Picked) => p.symbol || p.name;
  const series = shown.map((r) => ({
    label: label(r.pick),
    points: r.pts.map((pt) =>
      mode === "change"
        ? { date: pt.date, value: (pt.price / r.first.price - 1) * 100, note: price(pt.price) }
        : { date: pt.date, value: pt.price },
    ),
  }));
  const adjusted = rows.filter((r) => r.h?.adjusted);

  return (
    <div className="card" style={{ marginTop: 16 }}>
      <div className="card-head">
        <h2>Price history</h2>
        <div className="row">
          {picks.length > 1 && (
            <div className="row" style={{ marginRight: 8 }}>
              <button className={mode === "change" ? "primary" : ""} onClick={() => setMode("change")}>% change</button>
              <button className={mode === "price" ? "primary" : ""} onClick={() => setMode("price")}>Price</button>
            </div>
          )}
          {PERIODS.map((p) => (
            <button key={p.label} className={days === p.days ? "primary" : ""} onClick={() => setDays(p.days)}>
              {p.label}
            </button>
          ))}
        </div>
      </div>
      <p className="small muted">
        Closing prices and NAVs stored in Kosh's database. Add up to {MAX_SERIES} to compare them; with more than one,
        the chart shows each one's % change from the start of the period. Hover over the chart to read prices. To store
        more history, go to Settings &amp; data → Load past history.
      </p>
      {picks.length < MAX_SERIES ? (
        <InstrumentSearch
          onPick={add}
          placeholder={picks.length ? "Add another to compare" : "Search a share, fund, ETF or bond"}
        />
      ) : (
        <p className="small faint">Remove one to add another (up to {MAX_SERIES} at a time).</p>
      )}
      <ErrorNote error={error} />
      {picks.length > 0 && (
        <BusyOverlay busy={loading}>
          <div style={{ marginTop: 14 }}>
            <div className="row" style={{ flexWrap: "wrap", gap: 8 }}>
              {rows.map(({ pick, last, first, change }) => (
                <div key={pick.isin} className="series-chip" title={`${pick.name} · ${pick.isin}`}>
                  <i className="dot" style={{ background: SERIES_COLORS[pick.slot] }} />
                  <div style={{ minWidth: 0 }}>
                    <div className="name">{pick.name}</div>
                    <div className="small faint">
                      {KIND_LABEL[pick.kind] || pick.kind} · {pick.symbol || pick.isin}
                    </div>
                  </div>
                  {last && (
                    <div className="small" style={{ textAlign: "right", marginLeft: 6 }}>
                      <b>{price(last.price)}</b>
                      <div className="faint">{date(last.date)}</div>
                      {change != null && (
                        <div className={change >= 0 ? "up" : "down"} title={`since ${date(first.date)}`}>
                          {pct(change, 1, { sign: true })}
                        </div>
                      )}
                    </div>
                  )}
                  <button onClick={() => remove(pick.isin)} aria-label={`Remove ${pick.name}`} title="Remove">×</button>
                </div>
              ))}
            </div>
            {series.length > 0 ? (
              <MultiLineChart
                rebased={false}
                yFormat={mode === "change" ? (v) => pct(v / 100, 1, { sign: true }) : (v) => price(v)}
                colors={shown.map((r) => SERIES_COLORS[r.pick.slot])}
                series={series}
              />
            ) : (
              !loading && <div className="empty">Not enough stored prices in this period to draw a line.</div>
            )}
            {rows.some((r) => r.h && r.pts.length <= 1) && (
              <p className="small faint">
                {rows.filter((r) => r.h && r.pts.length <= 1).map((r) => label(r.pick)).join(", ")}: fewer than 2 stored
                prices in this period, so not drawn.
              </p>
            )}
            {adjusted.map((r) => (
              <p key={r.pick.isin} className="small faint">
                {label(r.pick)}: earlier prices are restated for{" "}
                {r.h!.actions.map(([d, f]) => `the ${date(d)} split/bonus (${actionLabel(f)})`).join(" and ")}, so the
                line shows the real change in value.
              </p>
            ))}
          </div>
        </BusyOverlay>
      )}
    </div>
  );
}

export default function Market() {
  const { data: events, error: eventsErr } = useApi<any[]>("/api/events");
  const [eventId, setEventId] = useState<number | null>(null);
  const selected = eventId ?? events?.[0]?.id ?? null;
  const { data: chart, error: chartErr, loading: chartLoading } = useApi<ChartResponse>(
    selected != null ? `/api/market/chart?event_id=${selected}` : null,
    [selected],
  );

  const change = (pts?: ChartSeries) => (pts && pts.length ? pts[pts.length - 1].value - 100 : null);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Market &amp; event impact</h1>
          <div className="sub">
            How a sector moved around an event, against the broader market — real NSE index data, not a guess.
          </div>
        </div>
      </div>
      <div className="card">
        <label className="field">
          Event
          <select value={selected ?? ""} onChange={(e) => setEventId(Number(e.target.value))}>
            {(events || []).map((e) => (
              <option key={e.id} value={e.id}>
                {date(e.date)} · {EVENT_KIND[e.kind] || e.kind} · {e.title}
              </option>
            ))}
          </select>
        </label>
        {events && events.length === 0 && <div className="empty">No events yet — log one from Events &amp; impact.</div>}
      </div>
      <ErrorNote error={eventsErr || chartErr} />
      {selected != null && !chart && !chartErr && <Loading label="Loading market data…" />}
      {chart && (
        <BusyOverlay busy={chartLoading}>
        <div className="card" style={{ marginTop: 16 }}>
          {chart.sector_index ? (
            <>
              <div className="card-head">
                <h2>{chart.sector} vs {chart.market_index}</h2>
                <span className="small faint">{date(chart.start)} – {date(chart.end)}</span>
              </div>
              <p className="small muted">
                {chart.sector}: <b className={(change(chart.series[chart.sector_index]) || 0) >= 0 ? "up" : "down"}>
                  {(change(chart.series[chart.sector_index]) ?? 0).toFixed(1)}%
                </b>
                {" vs "}
                {chart.market_index}:{" "}
                <b className={(change(chart.series[chart.market_index]) || 0) >= 0 ? "up" : "down"}>
                  {(change(chart.series[chart.market_index]) ?? 0).toFixed(1)}%
                </b>{" "}
                over this window.
              </p>
              <MultiLineChart
                series={[
                  { label: chart.sector || chart.sector_index, points: chart.series[chart.sector_index] || [] },
                  { label: chart.market_index, points: chart.series[chart.market_index] || [] },
                ]}
                eventDate={chart.event?.date}
              />
            </>
          ) : (
            <>
              <div className="card-head">
                <h2>{chart.market_index}</h2>
                <span className="small faint">{date(chart.start)} – {date(chart.end)}</span>
              </div>
              <p className="small muted">
                This event isn't tagged to a sector with its own index, so it's shown against the broad market only.
              </p>
              <MultiLineChart
                series={[{ label: chart.market_index, points: chart.series[chart.market_index] || [] }]}
                eventDate={chart.event?.date}
              />
            </>
          )}
        </div>
        </BusyOverlay>
      )}
      <PriceHistoryCard />
    </>
  );
}
