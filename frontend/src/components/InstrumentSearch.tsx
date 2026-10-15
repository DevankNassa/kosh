import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { KIND_LABEL } from "./ui";

export type InstrumentHit = {
  isin: string;
  name: string;
  symbol?: string;
  kind: string;
  asset_class: string;
  sub_class?: string;
  plan?: string;
};

export function InstrumentSearch({ onPick, placeholder }: { onPick: (i: InstrumentHit) => void; placeholder?: string }) {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<InstrumentHit[]>([]);
  const [open, setOpen] = useState(false);
  const timer = useRef<number>();
  useEffect(() => {
    window.clearTimeout(timer.current);
    if (q.trim().length < 2) {
      setHits([]);
      return;
    }
    timer.current = window.setTimeout(() => {
      api.get<InstrumentHit[]>(`/api/instruments/search?q=${encodeURIComponent(q)}`).then((h) => {
        setHits(h);
        setOpen(true);
      });
    }, 220);
  }, [q]);
  return (
    <div className="search">
      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        onFocus={() => hits.length && setOpen(true)}
        onBlur={() => window.setTimeout(() => setOpen(false), 150)}
        placeholder={placeholder || "Search fund, share, bond or ISIN"}
        style={{ width: "100%" }}
      />
      {open && hits.length > 0 && (
        <div className="search-results">
          {hits.map((h) => (
            <button
              key={h.isin}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => {
                onPick(h);
                setQ("");
                setOpen(false);
              }}
            >
              <div>{h.name}</div>
              <div className="small faint">
                {KIND_LABEL[h.kind] || h.kind} · {h.symbol || h.isin} {h.sub_class ? `· ${h.sub_class}` : ""}
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
