import { useState } from "react";
import { MultiLineChart } from "../components/Charts";
import { BusyOverlay, ErrorNote, Loading, useApi } from "../components/ui";
import { date } from "../format";
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
    </>
  );
}
