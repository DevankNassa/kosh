import { ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";

export function useApi<T = any>(url: string | null, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const seq = useRef(0);
  const load = useCallback(() => {
    if (!url) return;
    const n = ++seq.current;
    setLoading(true);
    setError(null);
    api
      .get<T>(url)
      .then((d) => n === seq.current && setData(d))
      .catch((e) => n === seq.current && setError(String(e.message || e)))
      .finally(() => n === seq.current && setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url, ...deps]);
  useEffect(load, [load]);
  return { data, error, loading, reload: load, setData };
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="loading">
      <span className="spinner" /> {label}
    </div>
  );
}

/** Keeps the previous content visible (dimmed) with a spinner on top while a
 * fresh fetch is in flight, instead of the delay looking like nothing changed. */
export function BusyOverlay({ busy, children }: { busy: boolean; children: ReactNode }) {
  return (
    <div className={"busy-wrap" + (busy ? " is-busy" : "")}>
      {children}
      {busy && (
        <div className="busy-indicator">
          <span className="spinner lg" />
        </div>
      )}
    </div>
  );
}

export function ErrorNote({ error }: { error: string | null }) {
  if (!error) return null;
  return <div className="notice bad">{error}</div>;
}

export function Stat({
  label,
  value,
  delta,
  deltaTone,
  hero,
  hint,
}: {
  label: string;
  value: ReactNode;
  delta?: ReactNode;
  deltaTone?: string;
  hero?: boolean;
  hint?: ReactNode;
}) {
  return (
    <div className="card stat">
      <div className="label">{label}</div>
      <div className={"value" + (hero ? " hero" : "")}>{value}</div>
      {delta !== undefined && <div className={"delta " + (deltaTone || "")}>{delta}</div>}
      {hint && <div className="small faint" style={{ marginTop: 4 }}>{hint}</div>}
    </div>
  );
}

export function Modal({
  title,
  onClose,
  children,
  footer,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
}) {
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  return (
    <div className="modal-back" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-label={title}>
        <h2>{title}</h2>
        {children}
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>
  );
}

export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
}: {
  tabs: { id: T; label: ReactNode }[];
  value: T;
  onChange: (t: T) => void;
}) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((t) => (
        <button key={t.id} role="tab" aria-selected={value === t.id} className={value === t.id ? "active" : ""} onClick={() => onChange(t.id)}>
          {t.label}
        </button>
      ))}
    </div>
  );
}

/** Small hover tooltip that follows the pointer. */
export function useTooltip() {
  const [tip, setTip] = useState<{ x: number; y: number; content: ReactNode } | null>(null);
  const show = (e: React.MouseEvent, content: ReactNode) => setTip({ x: e.clientX, y: e.clientY, content });
  const hide = () => setTip(null);
  const node = tip ? (
    <div
      className="tooltip"
      style={{
        left: Math.min(tip.x + 14, window.innerWidth - 290),
        top: tip.y + 14,
      }}
    >
      {tip.content}
    </div>
  ) : null;
  return { show, hide, node };
}

export const KIND_LABEL: Record<string, string> = {
  equity: "Share",
  mf: "Mutual fund",
  etf: "ETF",
  gsec: "G-Sec",
  sdl: "SDL",
  tbill: "T-Bill",
  corp_bond: "Bond",
  sgb: "SGB",
  reit_invit: "REIT/InvIT",
  other: "Other",
};

export function PriceBadge({ level, source }: { level?: string; source?: string }) {
  if (level === "model") return <span className="badge warn" title="No recent trade; priced from the yield curve plus a rating spread">Model price</span>;
  if (level === "stale") return <span className="badge bad" title={`Last price from ${source}`}>Stale price</span>;
  if (level === "missing") return <span className="badge bad">No price</span>;
  if (source === "statement") return <span className="badge">Statement</span>;
  return null;
}
