"use client";
import { Card, Empty, ErrorState, Loading, StatusBadge } from "@/components/ui";
import { Forecast, get, Page } from "@/lib/api";
import { day, num, pct, spct, tone, ts } from "@/lib/format";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { EvidencePanel } from "@/components/Evidence";

export default function Forecasts() {
  const [horizon, setHorizon] = useState(""); const [status, setStatus] = useState(""); const [symbol, setSymbol] = useState(""); const [history, setHistory] = useState(false);
  const [open, setOpen] = useState<number | null>(null);
  const { data, error, isLoading } = useQuery({ queryKey: ["forecasts", horizon, status, symbol, history], queryFn: () => get<Page<Forecast>>("/forecasts", { horizon, status, symbol, history, limit: 300 }) });
  const sel = useQuery({ queryKey: ["forecast", open], enabled: open !== null, queryFn: () => get<Forecast>(`/forecasts/${open}`) });
  return (
    <>
      <h1 className="text-xl font-semibold">Forecast explorer</h1>
      <Card>
        <div className="flex flex-wrap items-center gap-3">
          <input aria-label="Ticker" placeholder="Ticker" value={symbol} onChange={(e) => setSymbol(e.target.value)} className="w-28" />
          <select aria-label="Horizon" value={horizon} onChange={(e) => setHorizon(e.target.value)}><option value="">All horizons</option><option value="5">1 week</option><option value="21">1 month</option><option value="63">3 months</option><option value="126">6 months</option><option value="252">12 months</option></select>
          <select aria-label="Validation" value={status} onChange={(e) => setStatus(e.target.value)}><option value="">Any validation status</option><option value="validated">Validated OOS</option><option value="no_edge_over_baseline">No edge vs baseline</option><option value="poorly_calibrated">Poorly calibrated</option><option value="unstable">Unstable</option><option value="insufficient_data">Insufficient data</option></select>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={history} onChange={(e) => setHistory(e.target.checked)} /> Include superseded forecasts (history)</label>
        </div>
      </Card>
      {isLoading ? <Loading what="forecasts" /> : error ? <ErrorState error={error} /> : data!.items.length === 0 ? <Empty>No forecasts stored yet. Generate them with <code>python -m app.cli forecast</code> after ingesting data.</Empty> : (
        <div className="panel overflow-auto"><table className="dt"><thead><tr><th>Ticker</th><th>Horizon</th><th>P(up)</th><th>P(down)</th><th>Expected return</th><th>Prediction interval</th><th>Est. vol (ann.)</th><th>Validation</th><th>Model</th><th>Data cutoff</th><th>Generated</th><th></th></tr></thead><tbody>
          {data!.items.map((f) => (
            <tr key={f.id}>
              <td><Link className="lnk font-medium" href={`/assets/${f.instrument_id}`}>{f.symbol}</Link></td><td>{f.horizon_label}</td>
              <td className="num">{pct(f.prob_up, 0)}</td><td className="num">{pct(f.prob_down, 0)}</td><td className={`num ${tone(f.expected_return)}`}>{spct(f.expected_return)}</td>
              <td className="num" title={f.interval_method ?? ""}>{f.interval_low === null ? "—" : `${spct(f.interval_low)} … ${spct(f.interval_high)} (${pct(f.interval_level, 0)})`}</td>
              <td className="num">{pct(f.est_vol_ann)}</td><td><StatusBadge s={f.validation_status} /></td><td>{f.model_name} v{f.model_version}/{f.feature_version}</td><td>{day(f.data_cutoff)}</td><td>{ts(f.created_at)}</td>
              <td><button className="btn" onClick={() => setOpen(f.id)}>Evidence</button></td></tr>))}
        </tbody></table></div>)}
      {open !== null && (
        <Card title={`Evidence for forecast #${open}`} right={<button className="btn" onClick={() => setOpen(null)}>Close</button>}>
          {sel.isLoading ? <Loading /> : sel.error ? <ErrorState error={sel.error} /> : <EvidencePanel f={sel.data!} />}
        </Card>)}
    </>
  );
}
