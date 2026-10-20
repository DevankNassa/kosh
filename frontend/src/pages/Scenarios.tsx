import { useEffect, useState } from "react";
import { api } from "../api";
import { MultiLineChart } from "../components/Charts";
import { describeShock, ImpactView, Shock, ShockBuilder } from "../components/Impact";
import { BusyOverlay, ErrorNote, Loading, useApi } from "../components/ui";
import { date } from "../format";

// Fixed role -> colour, matching Kosh's existing asset-class colours (CLAUDE.md:
// "colour follows the asset class, never its rank"). Order matters: this exact
// sequence (debt, equity, gold, sector) is the one validated to keep every
// adjacent pair distinguishable under colour-blindness simulation.
const ROLE_COLOR: Record<string, string> = {
  debt: "var(--s-debt)",
  equity: "var(--s-equity)",
  gold: "var(--s-gold)",
  sector: "var(--s-other)",
};
const ROLE_ORDER = ["debt", "equity", "gold", "sector"];

type FamilySeries = { role: string; label: string; points: { date: string; value: number }[] };
type FamiliesChart = { event: { start: string; end: string }; mode: "families"; series: FamilySeries[] };
type SectorsChart = {
  event: { start: string; end: string };
  mode: "sectors";
  market: { label: string; points: { date: string; value: number }[] };
  sectors: FamilySeries[];
};

function delta(points: { value: number }[]): number | null {
  return points.length ? points[points.length - 1].value - 100 : null;
}

/** The single most informative number for a historical event's row: the
 * sector's own real move if it has one, else the market-wide move. */
function shockHeadline(s: Shock | Shock[]): { text: string; tone: "up" | "down" | "" } {
  const arr = Array.isArray(s) ? s : [s];
  const pick = arr.find((x) => x.filter?.sector) || arr[0];
  const pct = pick?.equity_move_pct;
  if (pct == null) return { text: "—", tone: "" };
  return { text: `${pct > 0 ? "+" : ""}${pct}%`, tone: pct > 0 ? "up" : pct < 0 ? "down" : "" };
}

function FamilyChart({ chart }: { chart: FamiliesChart }) {
  const ordered = [...chart.series].sort((a, b) => ROLE_ORDER.indexOf(a.role) - ROLE_ORDER.indexOf(b.role));
  return (
    <MultiLineChart
      series={ordered.map((s) => ({ label: s.label, points: s.points }))}
      colors={ordered.map((s) => ROLE_COLOR[s.role] || "var(--s-other)")}
      eventDate={chart.event.start}
    />
  );
}

function SectorGrid({ chart }: { chart: SectorsChart }) {
  return (
    <div className="grid g3">
      {chart.sectors.map((s) => {
        const d = delta(s.points);
        return (
          <div key={s.label} className="card" style={{ padding: 10 }}>
            <div className="row" style={{ justifyContent: "space-between", marginBottom: 4 }}>
              <span className="small" style={{ fontWeight: 560 }}>{s.label}</span>
              {d != null && <span className={"small num " + (d >= 0 ? "up" : "down")}>{d >= 0 ? "+" : ""}{d.toFixed(1)}%</span>}
            </div>
            <MultiLineChart
              compact
              height={70}
              series={[{ label: s.label, points: s.points }, { label: chart.market.label, points: chart.market.points }]}
              colors={["var(--s-equity)", "var(--text-3)"]}
              eventDate={chart.event.start}
            />
          </div>
        );
      })}
      <div className="small faint" style={{ gridColumn: "1 / -1" }}>
        Each tile: this sector (blue) vs {chart.market.label} (grey), rebased to 100 at the start of the window.
      </div>
    </div>
  );
}

const PRESETS: { label: string; shock: Shock }[] = [
  { label: "Rates −25 bps", shock: { yield_shift_bps: -25 } },
  { label: "Rates +50 bps", shock: { yield_shift_bps: 50 } },
  { label: "Nifty −10%", shock: { equity_move_pct: -10 } },
  { label: "Nifty −20%, rates −50 bps", shock: { equity_move_pct: -20, yield_shift_bps: -50 } },
  { label: "Credit stress (AA and below +150 bps)", shock: { spread_bps: 150, rating_buckets: ["AA", "A", "BBB", "Below BBB", "Unrated / unknown"] } },
  { label: "Gold +10%", shock: { gold_move_pct: 10 } },
];

type HistoricalEvent = { id: string; label: string; start: string; end: string; sector: string | null; shock: Shock | Shock[] };

export default function Scenarios() {
  const [mode, setMode] = useState<"hand" | "historical">("hand");
  const [shock, setShock] = useState<Shock>(PRESETS[2].shock);
  const { data: historical, error: historicalErr } = useApi<HistoricalEvent[]>("/api/scenario/historical");
  const [historicalId, setHistoricalId] = useState<string | null>(null);
  const [impact, setImpact] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [chartMode, setChartMode] = useState<"families" | "sectors">("families");
  const { data: chart, loading: chartLoading } = useApi<FamiliesChart | SectorsChart>(
    mode === "historical" && historicalId ? `/api/scenario/historical/${historicalId}/chart?mode=${chartMode}` : null,
    [mode, historicalId, chartMode],
  );

  useEffect(() => {
    if (mode !== "hand") return;
    setBusy(true); // show feedback immediately; the debounce below only delays the request, not the spinner
    const t = window.setTimeout(() => {
      api.post("/api/scenario", shock).then(setImpact).catch((e) => setErr(e.message)).finally(() => setBusy(false));
    }, 350);
    return () => window.clearTimeout(t);
  }, [mode, JSON.stringify(shock)]);

  useEffect(() => {
    if (mode !== "historical" || !historicalId) return;
    setBusy(true);
    api.post(`/api/scenario/historical/${historicalId}`).then(setImpact).catch((e) => setErr(e.message)).finally(() => setBusy(false));
  }, [mode, historicalId]);

  const active = historical?.find((h) => h.id === historicalId);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Scenarios</h1>
          <div className="sub">Stress every client portfolio at once. Results update as you change the inputs.</div>
        </div>
      </div>
      <div className="card">
        <div style={{ marginBottom: 6 }}>
          <div className="small" style={{ fontWeight: 650, color: "var(--text)" }}>Real historical events</div>
          <div className="small faint">The move shown is the real NSE index change over that window, not a guess</div>
        </div>
        <div className="option-list" style={{ marginBottom: 20 }}>
          {(historical || []).map((h) => {
            const isActive = mode === "historical" && historicalId === h.id;
            const head = shockHeadline(h.shock);
            return (
              <button
                key={h.id}
                className={"option-row" + (isActive ? " active" : "")}
                onClick={() => { setMode("historical"); setHistoricalId(h.id); }}
              >
                <span className="opt-check">{isActive && "✓"}</span>
                <span className="opt-main">
                  <span className="opt-title">{h.label}</span>
                  <span className="opt-sub">{date(h.start)} – {date(h.end)}{h.sector ? ` · ${h.sector}` : ""}</span>
                </span>
                <span className={"num " + head.tone} style={{ fontWeight: 650 }}>{head.text}</span>
              </button>
            );
          })}
          {historical && historical.length === 0 && <span className="small faint">No historical data cached yet.</span>}
        </div>
        <ErrorNote error={historicalErr} />

        <div style={{ marginBottom: 6 }}>
          <div className="small" style={{ fontWeight: 650, color: "var(--text)" }}>Hand-typed</div>
          <div className="small faint">Build your own what-if — pick a preset below, then adjust it</div>
        </div>
        <div className="chip-row" style={{ marginBottom: 12 }}>
          {PRESETS.map((p) => {
            const isActive = mode === "hand" && JSON.stringify(shock) === JSON.stringify(p.shock);
            return (
              <button
                key={p.label}
                className={isActive ? "active" : ""}
                onClick={() => { setMode("hand"); setShock(p.shock); }}
              >
                {isActive && "✓ "}{p.label}
              </button>
            );
          })}
        </div>

        {mode === "hand" && (
          <>
            <ShockBuilder value={shock} onChange={setShock} />
            <div className="small muted" style={{ marginTop: 8 }}>
              Scenario: <b>{describeShock(shock)}</b> {busy && <span className="spinner" style={{ verticalAlign: "middle", marginLeft: 6 }} />}
            </div>
          </>
        )}
        {mode === "historical" && active && (
          <div className="small muted" style={{ marginTop: 8 }}>
            {date(active.start)} – {date(active.end)} · what actually happened: <b>{describeShock(active.shock)}</b>
            {busy && <span className="spinner" style={{ verticalAlign: "middle", marginLeft: 6 }} />}
          </div>
        )}
      </div>

      {mode === "historical" && active && (
        <div className="card" style={{ marginTop: 16 }}>
          <div className="card-head">
            <h2>What moved, charted</h2>
            <div className="seg">
              <button className={chartMode === "families" ? "active" : ""} onClick={() => setChartMode("families")}>Fund families</button>
              <button className={chartMode === "sectors" ? "active" : ""} onClick={() => setChartMode("sectors")}>All sectors</button>
            </div>
          </div>
          {!chart ? (
            <Loading label="Loading market data…" />
          ) : (
            <BusyOverlay busy={chartLoading}>
              {chart.mode === "families" ? <FamilyChart chart={chart} /> : <SectorGrid chart={chart} />}
            </BusyOverlay>
          )}
        </div>
      )}

      <ErrorNote error={err} />
      <div style={{ marginTop: 16 }}>
        {!impact ? <Loading /> : <BusyOverlay busy={busy}><ImpactView impact={impact} /></BusyOverlay>}
      </div>
    </>
  );
}
