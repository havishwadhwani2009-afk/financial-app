"use client";
import { Evidence, Forecast } from "@/lib/api";
import { day, num, pct, spct } from "@/lib/format";
import { StatusBadge } from "./ui";

const label = (f: string) => f.replace(/_/g, " ");
function Row({ e, sign }: { e: Evidence; sign: 1 | -1 }) {
  return <li className="flex justify-between gap-3 text-sm"><span>{label(e.feature)} <span className="muted">= {num(e.value, 3)}{e.z !== null && e.z !== undefined ? ` (z ${e.z.toFixed(1)})` : ""}</span></span><span className={`num ${sign > 0 ? "text-emerald-600" : "text-red-600"}`}>{e.contribution !== null && e.contribution !== undefined ? `${sign > 0 ? "+" : ""}${e.contribution.toFixed(2)} log-odds` : ""}</span></li>;
}

export function EvidencePanel({ f }: { f: Forecast }) {
  const ev = f.evidence;
  return (
    <div className="space-y-4 text-sm">
      <div className="flex flex-wrap items-center gap-3"><StatusBadge s={f.validation_status} /><span className="muted">Model {f.model_name} v{f.model_version} · features {f.feature_version} · data cutoff {day(f.data_cutoff)} · horizon {f.horizon_label} ({f.horizon_days} trading days)</span></div>
      <div className="muted">P(up) {pct(f.prob_up, 1)} · expected return {spct(f.expected_return)} · {f.interval_low !== null ? `${pct(f.interval_level, 0)} interval ${spct(f.interval_low)} … ${spct(f.interval_high)}` : "no interval"} · realised vol (63d) {pct(f.hist_vol_ann)} · EWMA vol {pct(f.est_vol_ann)}</div>
      {f.interval_method && <div className="muted text-xs">Interval method: {f.interval_method}</div>}
      {!ev ? <div className="muted">No evidence stored for this forecast.</div> : (
        <>
          <div className="grid gap-4 md:grid-cols-2">
            <div><h3 className="mb-1 font-semibold">Supporting (bullish) model inputs</h3>{ev.bullish.length ? <ul className="space-y-1">{ev.bullish.map((e) => <Row key={e.feature} e={e} sign={1} />)}</ul> : <div className="muted">None — this model type has no signed contributions.</div>}</div>
            <div><h3 className="mb-1 font-semibold">Opposing (bearish) model inputs</h3>{ev.bearish.length ? <ul className="space-y-1">{ev.bearish.map((e) => <Row key={e.feature} e={e} sign={-1} />)}</ul> : <div className="muted">None.</div>}</div>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <div><h3 className="mb-1 font-semibold">Limitations</h3><ul className="list-disc space-y-1 pl-5">{ev.limitations.map((l, i) => <li key={i}>{l}</li>)}</ul></div>
            <div><h3 className="mb-1 font-semibold">What would invalidate it</h3><ul className="list-disc space-y-1 pl-5">{ev.invalidating_conditions.map((l, i) => <li key={i}>{l}</li>)}</ul></div>
          </div>
          <div className="muted text-xs">Out-of-sample backtest behind this status: {String(ev.backtest.n_obs)} observations ({String(ev.backtest.start_date)} → {String(ev.backtest.end_date)}), ~{Number(ev.backtest.effective_n ?? 0).toFixed(0)} independent; Brier skill vs baseline {ev.backtest.brier_skill === null ? "n/a" : Number(ev.backtest.brier_skill).toFixed(3)}; calibration error {ev.backtest.ece === null ? "n/a" : Number(ev.backtest.ece).toFixed(3)}. “Contribution” = coefficient × standardised value in the logistic model: a description of the model, not a causal explanation.</div>
        </>)}
    </div>
  );
}
