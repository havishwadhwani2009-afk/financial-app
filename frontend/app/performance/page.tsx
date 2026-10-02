"use client";
import { Card, Empty, ErrorState, Loading, StatusBadge } from "@/components/ui";
import { Backtest, get, Page } from "@/lib/api";
import { day, num, pct, spct, tone } from "@/lib/format";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis } from "recharts";

type Summary = { model: string; note: string; horizons: Record<string, { horizon_label: string; n_assets: number; status_counts: Record<string, number>; median_brier_skill: number | null; share_beating_baseline: number | null; median_ece: number | null; total_oos_obs: number }> };
type Detail = { summary: Backtest; config: Record<string, unknown>; metrics: { by_regime: Record<string, { n_obs: number; brier_skill: number; ece: number }>; regression: { mae: number; mae_baseline: number; rmse: number; rmse_baseline: number; oos_r2_vs_baseline: number } | null; classification: Record<string, number> | null }; calibration: { mean_pred: number; frac_positive: number; n: number }[]; strategy: null | { threshold: number; cost_bps_one_way: number; exposure: number; annual_turnover: number; n_days: number; note: string; strategy: Perf; buy_and_hold: Perf }; predictions: { asof_date: string; prob_up: number; baseline_prob_up: number; actual_return: number; pred_return: number }[]; predictions_note: string };
type Perf = { total_return: number; ann_return: number; ann_vol: number; sharpe_rf0: number | null; max_drawdown: number };
type Model = { id: number; name: string; version: string; feature_version: string; description: string; params: Record<string, unknown>; created_at: string };

export default function Performance() {
  const sum = useQuery({ queryKey: ["bt-sum"], queryFn: () => get<Summary>("/backtests/summary") });
  const list = useQuery({ queryKey: ["bt-list"], queryFn: () => get<Page<Backtest>>("/backtests", { model: "linear", limit: 500 }) });
  const models = useQuery({ queryKey: ["models"], queryFn: () => get<Model[]>("/models") });
  const [sel, setSel] = useState<number | null>(null);
  const det = useQuery({ queryKey: ["bt", sel], enabled: sel !== null, queryFn: () => get<Detail>(`/backtests/${sel}`) });
  return (
    <>
      <h1 className="text-xl font-semibold">Model performance</h1>
      <p className="muted text-sm">Every number below is <b>out-of-sample</b>: models are refit monthly on an expanding window using only labels already realised at the refit date (purged), then scored on later data. In-sample fit is never shown as performance.</p>
      <Card title="Aggregate by horizon (linear model vs unconditional-frequency baseline)">
        {sum.isLoading ? <Loading /> : sum.error ? <ErrorState error={sum.error} /> : Object.keys(sum.data!.horizons).length === 0 ? <Empty>No backtests stored yet. Ingest data, then run <code>python -m app.cli forecast</code>.</Empty> : (
          <>
            <table className="dt"><thead><tr><th>Horizon</th><th>Assets</th><th>OOS obs (overlapping)</th><th>Median Brier skill</th><th>Share beating baseline</th><th>Median calib. error</th><th>Validation outcomes</th></tr></thead><tbody>
              {Object.entries(sum.data!.horizons).map(([h, s]) => (<tr key={h}><td>{s.horizon_label} ({h}d)</td><td className="num">{s.n_assets}</td><td className="num">{s.total_oos_obs.toLocaleString()}</td><td className={`num ${tone(s.median_brier_skill)}`}>{num(s.median_brier_skill, 3)}</td><td className="num">{pct(s.share_beating_baseline, 0)}</td><td className="num">{num(s.median_ece, 3)}</td><td>{Object.entries(s.status_counts).map(([k, n]) => <span key={k} className="mr-2 inline-flex items-center gap-1"><StatusBadge s={k} />×{n}</span>)}</td></tr>))}
            </tbody></table>
            <p className="muted mt-2 text-xs">{sum.data!.note} Skill = 1 − Brier/Brier(baseline): positive means better than the base rate.</p>
          </>)}
      </Card>
      <Card title="Per asset and horizon">
        {list.isLoading ? <Loading /> : list.error ? <ErrorState error={list.error} /> : list.data!.items.length === 0 ? <Empty>Nothing to show.</Empty> : (
          <div className="max-h-96 overflow-auto"><table className="dt"><thead><tr><th>Ticker</th><th>Horizon</th><th>OOS obs</th><th>Period</th><th>Brier</th><th>Baseline</th><th>Skill</th><th>Log loss</th><th>Calib. err.</th><th>Bal. acc.</th><th>Status</th><th></th></tr></thead><tbody>
            {list.data!.items.map((b) => (<tr key={b.id}><td>{b.symbol}</td><td>{b.horizon_days}d</td><td className="num">{b.n_obs}</td><td>{day(b.start_date)} → {day(b.end_date)}</td><td className="num">{num(b.brier, 3)}</td><td className="num">{num(b.brier_baseline, 3)}</td><td className={`num ${tone(b.brier_skill)}`}>{num(b.brier_skill, 3)}</td><td className="num">{num(b.log_loss, 3)}</td><td className="num">{num(b.ece, 3)}</td><td className="num">{pct(b.balanced_accuracy, 0)}</td><td><StatusBadge s={b.validation_status} /></td><td><button className="btn" onClick={() => setSel(b.id)}>Detail</button></td></tr>))}
          </tbody></table></div>)}
      </Card>
      {sel !== null && (
        <Card title={`Backtest #${sel} detail`} right={<button className="btn" onClick={() => setSel(null)}>Close</button>}>
          {det.isLoading ? <Loading /> : det.error ? <ErrorState error={det.error} /> : <DetailView d={det.data!} />}
        </Card>)}
      <Card title="Model version history">
        {models.isLoading ? <Loading /> : models.error ? <ErrorState error={models.error} /> : models.data!.length === 0 ? <Empty>No model versions registered yet.</Empty> : (
          <table className="dt"><thead><tr><th>Name</th><th>Version</th><th>Features</th><th>Description</th><th>Hyper-parameters (fixed a priori)</th><th>Registered</th></tr></thead><tbody>
            {models.data!.map((m) => (<tr key={m.id}><td>{m.name}</td><td>{m.version}</td><td>{m.feature_version}</td><td className="whitespace-normal">{m.description}</td><td className="font-mono text-xs">{JSON.stringify(m.params)}</td><td>{day(m.created_at)}</td></tr>))}
          </tbody></table>)}
      </Card>
    </>
  );
}

function DetailView({ d }: { d: Detail }) {
  const s = d.summary; const cal = d.calibration ?? [];
  const pts = d.predictions.map((p) => ({ date: p.asof_date, pred: p.pred_return, actual: p.actual_return, prob: p.prob_up, base: p.baseline_prob_up }));
  return (
    <div className="space-y-5 text-sm">
      <div className="muted">{s.symbol} · {s.model_name} · {s.horizon_days}-day horizon · {s.n_obs} OOS observations ({day(s.start_date)} → {day(s.end_date)}) · ~{(s.n_obs / s.horizon_days).toFixed(0)} independent · {JSON.stringify(d.config)}</div>
      {s.validation_reasons?.map((r, i) => <div key={i} className="rounded bg-zinc-100 px-3 py-1 dark:bg-zinc-800">{r}</div>)}
      <div className="grid gap-5 lg:grid-cols-2">
        <div><h3 className="mb-1 font-semibold">Calibration (reliability) — OOS</h3>
          <div className="h-64"><ResponsiveContainer><ScatterChart margin={{ left: 0, right: 10 }}><CartesianGrid strokeOpacity={0.15} /><XAxis type="number" dataKey="mean_pred" domain={[0, 1]} name="Predicted" tick={{ fontSize: 11 }} /><YAxis type="number" dataKey="frac_positive" domain={[0, 1]} name="Observed" tick={{ fontSize: 11 }} width={40} /><Tooltip formatter={(v: number) => v.toFixed(2)} /><ReferenceLine segment={[{ x: 0, y: 0 }, { x: 1, y: 1 }]} strokeDasharray="4 4" /><Scatter data={cal} fill="var(--accent)" /></ScatterChart></ResponsiveContainer></div>
          <p className="muted text-xs">Points on the dashed diagonal = perfectly calibrated. Bin counts: {cal.map((c) => c.n).join(", ")}.</p></div>
        <div><h3 className="mb-1 font-semibold">Forecast vs outcome (every 5th date)</h3>
          <div className="h-64"><ResponsiveContainer><LineChart data={pts}><CartesianGrid strokeOpacity={0.15} /><XAxis dataKey="date" tick={{ fontSize: 11 }} minTickGap={60} /><YAxis tick={{ fontSize: 11 }} width={45} tickFormatter={(v) => `${(v * 100).toFixed(0)}%`} /><Tooltip formatter={(v: number) => spct(v)} /><Line dataKey="actual" name="Realised return" dot={false} stroke="#888" strokeWidth={1} isAnimationActive={false} /><Line dataKey="pred" name="Predicted return" dot={false} stroke="var(--accent)" strokeWidth={1.5} isAnimationActive={false} /></LineChart></ResponsiveContainer></div></div>
      </div>
      {d.metrics.regression && <div>MAE {pct(d.metrics.regression.mae, 2)} vs baseline {pct(d.metrics.regression.mae_baseline, 2)} · RMSE {pct(d.metrics.regression.rmse, 2)} vs {pct(d.metrics.regression.rmse_baseline, 2)} · OOS R² vs baseline {num(d.metrics.regression.oos_r2_vs_baseline, 3)}</div>}
      {Object.keys(d.metrics.by_regime ?? {}).length > 0 && <div><h3 className="mb-1 font-semibold">By trend regime (≥100 obs only)</h3>{Object.entries(d.metrics.by_regime).map(([k, v]) => <div key={k}>{k}: n={v.n_obs}, Brier skill {num(v.brier_skill, 3)}, calib. error {num(v.ece, 3)}</div>)}</div>}
      {d.strategy && (
        <div><h3 className="mb-1 font-semibold">Illustrative long/cash rule (P(up) &gt; {d.strategy.threshold}), costs {d.strategy.cost_bps_one_way} bp one-way</h3>
          <table className="dt"><thead><tr><th></th><th>Total return</th><th>Ann. return</th><th>Ann. vol</th><th>Sharpe (rf=0)</th><th>Max drawdown</th></tr></thead><tbody>
            {([["Strategy", d.strategy.strategy], ["Buy & hold", d.strategy.buy_and_hold]] as [string, Perf][]).map(([l, p]) => <tr key={l}><td>{l}</td><td className="num">{spct(p.total_return)}</td><td className="num">{spct(p.ann_return)}</td><td className="num">{pct(p.ann_vol)}</td><td className="num">{num(p.sharpe_rf0)}</td><td className="num">{pct(p.max_drawdown)}</td></tr>)}
          </tbody></table>
          <p className="muted mt-1 text-xs">Exposure {pct(d.strategy.exposure, 0)} · annual turnover {num(d.strategy.annual_turnover, 1)}x · {d.strategy.n_days} days. {d.strategy.note} A single-asset result is not evidence of profitability.</p></div>)}
    </div>
  );
}
