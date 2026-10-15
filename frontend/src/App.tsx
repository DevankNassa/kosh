import { createContext, useContext } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import { useApi } from "./components/ui";
import { date, num, pct } from "./format";
import ClientDetail from "./pages/ClientDetail";
import Clients from "./pages/Clients";
import Dashboard from "./pages/Dashboard";
import Events from "./pages/Events";
import ImportPage from "./pages/Import";
import Scenarios from "./pages/Scenarios";
import Settings from "./pages/Settings";

export type Status = {
  market: any;
  market_asof: string;
  yield_curve: { asof: string | null; points: [number, number][]; source: string } | null;
  indices: { asof: string; items: { name: string; close: number; change_pct: number | null }[] } | null;
  settings: { distributor_name: string; arn: string; firm_name: string };
  clients: number;
  demo_clients: number;
  disclaimer: string;
};

const StatusCtx = createContext<{ status: Status | null; reload: () => void }>({ status: null, reload: () => {} });
export const useStatus = () => useContext(StatusCtx);

const Icon = ({ d }: { d: string }) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
    <path d={d} />
  </svg>
);

const NAV = [
  { to: "/", label: "Morning review", icon: "M3 12h4l3-8 4 16 3-8h4" },
  { to: "/clients", label: "Clients", icon: "M16 19v-1a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v1M9 10a3 3 0 1 0 0-6 3 3 0 0 0 0 6M22 19v-1a4 4 0 0 0-3-3.9M16 4.1a3 3 0 0 1 0 5.8" },
  { to: "/events", label: "Events & impact", icon: "M12 3v18M3 12h18M5.6 5.6l12.8 12.8" },
  { to: "/scenarios", label: "Scenarios", icon: "M4 19V5M4 19h16M8 15l4-4 3 3 5-6" },
  { to: "/import", label: "Import statement", icon: "M12 3v12M7 10l5 5 5-5M5 21h14" },
  { to: "/settings", label: "Settings & data", icon: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" },
];

function MarketStrip({ status }: { status: Status | null }) {
  const items = status?.indices?.items || [];
  return (
    <div className="topbar">
      <span className="faint">Market close {date(status?.market_asof)}</span>
      {items.map((i) => (
        <span className="ticker" key={i.name}>
          <span className="name">{i.name.replace("Nifty 10 yr Benchmark G-Sec", "10Y G-Sec index")}</span>
          <b>{num(i.close, 2)}</b>
          {i.change_pct != null && (
            <span className={i.change_pct > 0 ? "up" : i.change_pct < 0 ? "down" : ""}>{pct(i.change_pct / 100, 2, { sign: true })}</span>
          )}
        </span>
      ))}
    </div>
  );
}

export default function App() {
  const { data: status, reload } = useApi<Status>("/api/status");
  const s = status?.settings;
  return (
    <StatusCtx.Provider value={{ status, reload }}>
      <div className="shell">
        <aside className="sidebar">
          <div className="brand">
            <div className="brand-mark">K</div>
            <div>
              <div className="brand-name">Kosh</div>
              <div className="brand-sub">Portfolio review</div>
            </div>
          </div>
          <nav className="nav">
            {NAV.map((n) => (
              <NavLink key={n.to} to={n.to} end={n.to === "/"}>
                <Icon d={n.icon} />
                {n.label}
              </NavLink>
            ))}
          </nav>
          <div className="sidebar-foot">
            {s && (
              <>
                <div style={{ color: "var(--text-2)", fontWeight: 600 }}>{s.distributor_name}</div>
                <div>AMFI-registered Mutual Fund Distributor</div>
                <div>{s.arn}</div>
              </>
            )}
          </div>
        </aside>
        <div className="main">
          <MarketStrip status={status} />
          <main className="content">
            <Routes>
              <Route path="/" element={<Dashboard />} />
              <Route path="/clients" element={<Clients />} />
              <Route path="/clients/:id" element={<ClientDetail />} />
              <Route path="/events" element={<Events />} />
              <Route path="/events/:id" element={<Events />} />
              <Route path="/scenarios" element={<Scenarios />} />
              <Route path="/import" element={<ImportPage />} />
              <Route path="/settings" element={<Settings />} />
            </Routes>
          </main>
          <footer className="footer">
            {status?.disclaimer}
            {s && ` ${s.distributor_name}, AMFI-registered Mutual Fund Distributor, ${s.arn}.`}
          </footer>
        </div>
      </div>
    </StatusCtx.Provider>
  );
}
