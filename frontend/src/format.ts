// Indian number formatting: lakh (1,00,000) and crore (1,00,00,000).

const inrFull = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
const inr2 = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2, minimumFractionDigits: 2 });

export function inr(v: number | null | undefined, opts: { sign?: boolean } = {}): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const s = opts.sign && v > 0 ? "+" : v < 0 ? "−" : "";
  return `${s}₹${inrFull.format(Math.abs(v))}`;
}

/** Compact: ₹4.93 Cr, ₹12.4 L, ₹85,000 */
export function inrc(v: number | null | undefined, opts: { sign?: boolean } = {}): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const a = Math.abs(v);
  const s = opts.sign && v > 0 ? "+" : v < 0 ? "−" : "";
  if (a >= 1e7) return `${s}₹${(a / 1e7).toFixed(a >= 1e9 ? 0 : 2)} Cr`;
  if (a >= 1e5) return `${s}₹${(a / 1e5).toFixed(a >= 1e7 ? 0 : 1)} L`;
  return `${s}₹${inrFull.format(a)}`;
}

export function price(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return `₹${inr2.format(v)}`;
}

export function pct(v: number | null | undefined, digits = 1, opts: { sign?: boolean } = {}): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const s = opts.sign && v > 0 ? "+" : v < 0 ? "−" : "";
  return `${s}${(Math.abs(v) * 100).toFixed(digits)}%`;
}

export function num(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined) return "—";
  return new Intl.NumberFormat("en-IN", { maximumFractionDigits: digits }).format(v);
}

export function date(v: string | null | undefined): string {
  if (!v) return "—";
  const d = new Date(v.length === 10 ? v + "T00:00:00" : v);
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

export function tone(v: number | null | undefined): string {
  if (!v) return "";
  return v > 0 ? "up" : "down";
}

export const ASSET_LABEL: Record<string, string> = {
  equity: "Equity",
  debt: "Debt",
  hybrid: "Hybrid",
  gold: "Gold & silver",
  other: "Other",
};

export function titleCase(s: string): string {
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : s;
}
