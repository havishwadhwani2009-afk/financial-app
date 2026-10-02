export const pct = (v: number | null | undefined, d = 1) => (v === null || v === undefined || Number.isNaN(v) ? "—" : `${(v * 100).toFixed(d)}%`);
export const spct = (v: number | null | undefined, d = 1) => (v === null || v === undefined || Number.isNaN(v) ? "—" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(d)}%`);
export const num = (v: number | null | undefined, d = 2) => (v === null || v === undefined || Number.isNaN(v) ? "—" : v.toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: d }));
export const big = (v: number | null | undefined) => {
  if (v === null || v === undefined) return "—";
  const a = Math.abs(v);
  return a >= 1e12 ? `${(v / 1e12).toFixed(2)}T` : a >= 1e9 ? `${(v / 1e9).toFixed(2)}B` : a >= 1e6 ? `${(v / 1e6).toFixed(1)}M` : v.toLocaleString();
};
export const day = (s: string | null | undefined) => (s ? s.slice(0, 10) : "—");
export const ts = (s: string | null | undefined) => (s ? s.replace("T", " ").slice(0, 16) + " UTC" : "—");
export const tone = (v: number | null | undefined) => (v === null || v === undefined ? "" : v > 0 ? "text-emerald-600 dark:text-emerald-400" : v < 0 ? "text-red-600 dark:text-red-400" : "");
