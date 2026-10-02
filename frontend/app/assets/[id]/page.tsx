"use client";
import { EvidencePanel } from "@/components/Evidence";
import { Card, Empty, ErrorState, Loading, Stat, StatusBadge } from "@/components/ui";
import { Asset, Backtest, Forecast, get, Page, PriceSeries } from "@/lib/api";
import { big, day, num, pct, spct, tone, ts } from "@/lib/format";
import { useQuery } from "@tanstack/react-query";
import { use, useMemo, useState } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

type Period = { period_end: string; publicly_available_from: string; restated: boolean; values: Record<string, number>; metrics: Record<string, number | null> };
type Fund = { cik: string | null; periods: Period[]; warnings: string[]; definitions: Record<string, string>; source: string; currency: string; valuation: null | { price: number | null; price_date: string | null; market_cap: number | null; pe: number | null; ps: number | null; fcf_yield: number | null; ev_revenue: number | null; inputs: Record<string, string | null>; notes: string[] } };
type Etf = { category: string | null; risk: null | { ann_vol_1y: number; max_drawdown_full_history: number; current_drawdown: number; worst_day: number; obs: number }; unavailable_reason: string; holdings: unknown; expense_ratio: number | null; currency: string | null };
type Scen = { available: boolean; reason?: string; n_weeks?: number; window?: string[]; r_squared?: number; betas?: Record<string, { beta: number; t_stat: number; significant_95: boolean; description: string }>; scenarios?: { scenario: string; implied_asset_move: number; beta_uncertainty_95: number[]; reliable: boolean }[]; caveats?: string[] };

const RANGES: [string, number][] = [["1M", 21], ["6M", 126], ["1Y", 252], ["5Y", 1260], ["Max", 100000]];

export default function AssetPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const asset = useQuery({ queryKey: ["asset", id], queryFn: () => get<Asset>(`/assets/${id}`) });
  const prices = useQuery({ queryKey: ["prices", id], queryFn: () => get<PriceSeries>(`/assets/${id}/prices`, { limit: 20000 }) });
  const fcs = useQuery({ queryKey: ["asset-fc", id], queryFn: () => get<Forecast[]>(`/assets/${id}/forecasts`) });
  const a = asset.data;
  if (asset.isLoading) return <Loading what="asset" />;
  if (asset.error) return <ErrorState error={asset.error} />;
  return (
    <>
      <div>
        <h1 className="text-xl font-semibold">{a!.symbol} <span className="muted text-base font-normal">{a!.name ?? "name unavailable"}</span></h1>
        <p className="muted text-xs">{a!.instrument_type.toUpperCase()} · {a!.exchange} · {a!.sector ?? "sector unavailable"}{a!.industry ? ` · ${a!.industry}` : ""} · {a!.currency ?? "currency unavailable"} · internal id {a!.id}{a!.cik ? ` · SEC CIK ${a!.cik}` : ""} · metadata source: {a!.metadata_source ?? "n/a"}</p>
      </div>
      <PriceCard q={prices} />
      <ForecastCard q={fcs} />
      {a!.instrument_type === "stock" ? <FundCard id={id} /> : <EtfCard id={id} />}
      <ScenarioCard id={id} />
      <BacktestCard id={id} />
    </>
  );
}

function PriceCard({ q }: { q: ReturnType<typeof useQuery<PriceSeries>> }) {
  const [rng, setRng] = useState(252);
  const data = useMemo(() => (q.data?.prices ?? []).slice(-rng).map((p) => ({ date: p.date, price: p.adj_close ?? p.close })), [q.data, rng]);
  return (
    <Card title="Price history (adjusted close)" right={<div className="flex gap-1">{RANGES.map(([l, n]) => <button key={l} className="btn" aria-pressed={rng === n} onClick={() => setRng(n)}>{l}</button>)}</div>}>
      {q.isLoading ? <Loading /> : q.error ? <ErrorState error={q.error} /> : data.length === 0 ? <Empty>No prices ingested for this instrument.</Empty> : (
        <>
          {q.data!.stale && <div className="mb-2 rounded bg-amber-100 px-3 py-1 text-xs text-amber-900 dark:bg-amber-950 dark:text-amber-200">Stale: last price {day(q.data!.last_date)}.</div>}
          <div className="h-72"><ResponsiveContainer><LineChart data={data}><CartesianGrid strokeOpacity={0.15} /><XAxis dataKey="date" tick={{ fontSize: 11 }} minTickGap={50} /><YAxis domain={["auto", "auto"]} tick={{ fontSize: 11 }} width={50} /><Tooltip formatter={(v: number) => num(v)} /><Line dataKey="price" dot={false} stroke="var(--accent)" strokeWidth={1.5} isAnimationActive={false} /></LineChart></ResponsiveContainer></div>
          <p className="muted mt-1 text-xs">{q.data!.count} daily bars · source: {q.data!.prices[q.data!.prices.length - 1].provider} · last bar {day(q.data!.last_date)} · ingested {ts(q.data!.last_ingested_at)}. Prices may be delayed.</p>
        </>)}
    </Card>
  );
}

function ForecastCard({ q }: { q: ReturnType<typeof useQuery<Forecast[]>> }) {
  const [open, setOpen] = useState<number | null>(null);
  return (
    <Card title="Forecasts by horizon (model estimates)">
      {q.isLoading ? <Loading /> : q.error ? <ErrorState error={q.error} /> : q.data!.length === 0 ? <Empty>No forecast stored for this asset (needs ≥ 300 price rows and a forecast run).</Empty> : (
        <>
          <table className="dt"><thead><tr><th>Horizon</th><th>P(up)</th><th>Expected return</th><th>Interval</th><th>Est. vol</th><th>Validation</th><th>Data cutoff</th><th>Model</th><th></th></tr></thead><tbody>
            {q.data!.map((f) => (<tr key={f.id}><td>{f.horizon_label}</td><td className="num">{pct(f.prob_up, 0)}</td><td className={`num ${tone(f.expected_return)}`}>{spct(f.expected_return)}</td>
              <td className="num" title={f.interval_method ?? ""}>{f.interval_low === null ? "—" : `${spct(f.interval_low)} … ${spct(f.interval_high)}`}</td><td className="num">{pct(f.est_vol_ann)}</td><td><StatusBadge s={f.validation_status} /></td><td>{day(f.data_cutoff)}</td><td>{f.model_name} v{f.model_version}</td>
              <td><button className="btn" onClick={() => setOpen(open === f.id ? null : f.id)}>{open === f.id ? "Hide" : "Evidence"}</button></td></tr>))}
          </tbody></table>
          {open && <div className="mt-4 border-t pt-4" style={{ borderColor: "var(--line)" }}><EvidencePanel f={q.data!.find((f) => f.id === open)!} /></div>}
          <p className="muted mt-3 text-xs">Probabilities are only meaningful where validation is “Validated OOS”; otherwise treat them as uninformative relative to the historical base rate.</p>
        </>)}
    </Card>
  );
}

const ROWS: [string, string, "v" | "m", "big" | "pct" | "num"][] = [
  ["Revenue", "revenue", "v", "big"], ["Revenue growth", "revenue_growth", "m", "pct"], ["Gross margin", "gross_margin", "m", "pct"], ["Operating margin", "operating_margin", "m", "pct"],
  ["Net income", "net_income", "v", "big"], ["Net income growth", "net_income_growth", "m", "pct"], ["Net margin", "net_margin", "m", "pct"], ["Diluted EPS", "eps_diluted", "v", "num"],
  ["Operating cash flow", "cfo", "v", "big"], ["Free cash flow", "fcf", "m", "big"], ["Return on equity", "roe", "m", "pct"], ["Total debt", "total_debt", "m", "big"], ["Cash", "cash", "v", "big"],
  ["Debt / equity", "debt_to_equity", "m", "num"], ["Interest coverage (x)", "interest_coverage", "m", "num"],
];

function FundCard({ id }: { id: string }) {
  const q = useQuery({ queryKey: ["fund", id], queryFn: () => get<Fund>(`/assets/${id}/fundamentals`) });
  const f = q.data;
  const fmt = (x: number | null | undefined, k: "big" | "pct" | "num") => (x === null || x === undefined ? "—" : k === "big" ? big(x) : k === "pct" ? pct(x) : num(x));
  return (
    <Card title="Fundamentals (SEC XBRL, annual filings)">
      {q.isLoading ? <Loading /> : q.error ? <ErrorState error={q.error} /> : (
        <>
          {f!.warnings.map((w, i) => <div key={i} className="mb-2 rounded bg-amber-100 px-3 py-1 text-xs text-amber-900 dark:bg-amber-950 dark:text-amber-200">{w}</div>)}
          {f!.periods.length > 0 && (
            <div className="overflow-auto"><table className="dt"><thead><tr><th>Fiscal period end</th>{f!.periods.slice(-6).map((p) => <th key={p.period_end} className="num">{p.period_end}</th>)}</tr><tr><th className="muted font-normal">Public from</th>{f!.periods.slice(-6).map((p) => <th key={p.period_end} className="muted font-normal">{p.publicly_available_from}{p.restated ? " (restated)" : ""}</th>)}</tr></thead><tbody>
              {ROWS.map(([label, key, src, kind]) => (<tr key={key}><td title={f!.definitions[key] ?? ""}>{label}</td>{f!.periods.slice(-6).map((p) => <td key={p.period_end} className="num">{fmt(src === "v" ? p.values[key] : p.metrics[key], kind)}</td>)}</tr>))}
            </tbody></table></div>)}
          {f!.valuation && f!.valuation.price !== null && (
            <div className="mt-4 grid grid-cols-2 gap-4 sm:grid-cols-5"><Stat label="Market cap" value={big(f!.valuation.market_cap)} sub={`shares as of ${f!.valuation.inputs.shares_as_of ?? "n/a"}`} /><Stat label="P/E" value={num(f!.valuation.pe, 1)} /><Stat label="P/S" value={num(f!.valuation.ps, 1)} /><Stat label="FCF yield" value={pct(f!.valuation.fcf_yield)} /><Stat label="EV / revenue" value={num(f!.valuation.ev_revenue, 1)} /></div>)}
          {f!.valuation?.notes.map((n, i) => <p key={i} className="muted mt-2 text-xs">{n}</p>)}
          <details className="mt-3 text-xs"><summary className="cursor-pointer">Definitions & limitations</summary><ul className="mt-2 list-disc space-y-1 pl-5">{Object.entries(f!.definitions).map(([k, v]) => <li key={k}><b>{k}</b>: {v}</li>)}<li>Source: {f!.source}. Currency: {f!.currency}. No composite quality score is computed. No peer comparison is shown (no validated peer groups).</li></ul></details>
        </>)}
    </Card>
  );
}

function EtfCard({ id }: { id: string }) {
  const q = useQuery({ queryKey: ["etf", id], queryFn: () => get<Etf>(`/assets/${id}/etf`) });
  return (
    <Card title="Fund information">
      {q.isLoading ? <Loading /> : q.error ? <ErrorState error={q.error} /> : (
        <>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-5"><Stat label="Category (manual label)" value={q.data!.category ?? "—"} /><Stat label="Expense ratio" value="unavailable" /><Stat label="Holdings / exposures" value="unavailable" /><Stat label="1Y volatility" value={pct(q.data!.risk?.ann_vol_1y)} /><Stat label="Max drawdown (history)" value={pct(q.data!.risk?.max_drawdown_full_history)} sub={`current ${pct(q.data!.risk?.current_drawdown)}`} /></div>
          <p className="muted mt-3 text-xs">{q.data!.unavailable_reason}</p>
        </>)}
    </Card>
  );
}

function ScenarioCard({ id }: { id: string }) {
  const q = useQuery({ queryKey: ["scen", id], queryFn: () => get<Scen>(`/assets/${id}/scenarios`) });
  return (
    <Card title="Scenario sensitivities (historical co-movement — not a forecast)">
      {q.isLoading ? <Loading /> : q.error ? <ErrorState error={q.error} /> : !q.data!.available ? <Empty>{q.data!.reason}</Empty> : (
        <>
          <table className="dt"><thead><tr><th>Scenario</th><th>Implied asset move</th><th>Coefficient 95% band</th><th>Reliability</th></tr></thead><tbody>
            {q.data!.scenarios!.map((s) => (<tr key={s.scenario}><td>{s.scenario}</td><td className={`num ${tone(s.implied_asset_move)}`}>{spct(s.implied_asset_move)}</td><td className="num">{spct(s.beta_uncertainty_95[0])} … {spct(s.beta_uncertainty_95[1])}</td><td>{s.reliable ? "coefficients significant" : "not statistically significant"}</td></tr>))}
          </tbody></table>
          <p className="muted mt-2 text-xs">{q.data!.n_weeks} weekly observations ({q.data!.window![0]} → {q.data!.window![1]}), R² {num(q.data!.r_squared, 2)}. {q.data!.caveats!.join(" ")}</p>
        </>)}
    </Card>
  );
}

function BacktestCard({ id }: { id: string }) {
  const q = useQuery({ queryKey: ["bt", id], queryFn: async () => { const a = await get<Asset>(`/assets/${id}`); return get<Page<Backtest>>("/backtests", { symbol: a.symbol, model: "linear", limit: 20 }); } });
  return (
    <Card title="Historical model performance for this asset (walk-forward, out-of-sample)">
      {q.isLoading ? <Loading /> : q.error ? <ErrorState error={q.error} /> : q.data!.items.length === 0 ? <Empty>No backtest stored.</Empty> : (
        <table className="dt"><thead><tr><th>Horizon</th><th>OOS obs</th><th>Period</th><th>Brier</th><th>Baseline Brier</th><th>Skill</th><th>Calib. error</th><th>Dir. acc.</th><th>MAE / baseline</th><th>Status</th></tr></thead><tbody>
          {q.data!.items.sort((a, b) => a.horizon_days - b.horizon_days).map((b) => (<tr key={b.id}><td>{b.horizon_days}d</td><td className="num">{b.n_obs}</td><td>{day(b.start_date)} → {day(b.end_date)}</td><td className="num">{num(b.brier, 3)}</td><td className="num">{num(b.brier_baseline, 3)}</td><td className={`num ${tone(b.brier_skill)}`}>{num(b.brier_skill, 3)}</td><td className="num">{num(b.ece, 3)}</td><td className="num">{pct(b.directional_accuracy)}</td><td className="num">{pct(b.mae)} / {pct(b.mae_baseline)}</td><td><StatusBadge s={b.validation_status} /></td></tr>))}
        </tbody></table>)}
    </Card>
  );
}
