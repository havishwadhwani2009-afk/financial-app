"use client";
import { Card, Empty, ErrorState, Loading } from "@/components/ui";
import { get } from "@/lib/api";
import { day, num } from "@/lib/format";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

type Series = { series_id: string; title: string; category: string; units: string | null; frequency: string | null; latest_observation_date: string | null; latest_published_date: string | null; latest_value: number | null };
type Obs = { series_id: string; title: string; units: string; note: string; observations: { observation_date: string; published_date: string; value: number; pit_quality: string }[] };
type Pillars = { as_of: string; method: string; pillars: Record<string, { title: string; score: number | null; label: string | null; inputs: { series: string; description: string; status: string; z?: number; sign?: number; weight?: number; latest_transformed?: number; observation_date?: string; published_date?: string; transform?: string }[] }> };
const GROUPS = ["rates", "inflation", "liquidity", "growth", "dollar", "credit", "volatility"];

export default function Macro() {
  const list = useQuery({ queryKey: ["macro-list"], queryFn: () => get<Series[]>("/macro/series") });
  const pil = useQuery({ queryKey: ["pillars"], queryFn: () => get<Pillars>("/macro/pillars") });
  const [sel, setSel] = useState<string>("DGS10");
  const obs = useQuery({ queryKey: ["obs", sel], queryFn: () => get<Obs>(`/macro/series/${sel}`, { limit: 3000 }), enabled: !!list.data?.some((s) => s.series_id === sel) });
  return (
    <>
      <h1 className="text-xl font-semibold">Macro dashboard</h1>
      {list.isLoading ? <Loading /> : list.error ? <ErrorState error={list.error} /> : list.data!.length === 0 ? <Empty>No macro series ingested yet (FRED). See README.</Empty> : (
        <div className="grid gap-4 lg:grid-cols-[320px_1fr]">
          <Card title="Series">
            <div className="max-h-[480px] space-y-3 overflow-auto">{GROUPS.map((g) => { const items = list.data!.filter((s) => s.category === g); return items.length ? (
              <div key={g}><div className="muted mb-1 text-xs font-semibold uppercase">{g}</div>{items.map((s) => (
                <button key={s.series_id} onClick={() => setSel(s.series_id)} className={`block w-full rounded px-2 py-1 text-left text-sm ${sel === s.series_id ? "bg-blue-600/10 font-medium" : ""}`}>{s.title}<span className="muted block text-xs">{num(s.latest_value)} · obs {day(s.latest_observation_date)} · pub {day(s.latest_published_date)}</span></button>))}</div>) : null; })}</div>
          </Card>
          <Card title={obs.data?.title ?? sel}>
            {obs.isLoading ? <Loading /> : obs.error ? <ErrorState error={obs.error} /> : !obs.data ? <Empty>Series not ingested.</Empty> : (
              <>
                <div className="h-80"><ResponsiveContainer><LineChart data={obs.data.observations}><CartesianGrid strokeOpacity={0.15} /><XAxis dataKey="observation_date" tick={{ fontSize: 11 }} minTickGap={60} /><YAxis domain={["auto", "auto"]} tick={{ fontSize: 11 }} width={55} /><Tooltip formatter={(v: number) => num(v, 3)} labelFormatter={(l) => `observed ${l}`} /><Line dataKey="value" dot={false} stroke="var(--accent)" strokeWidth={1.5} isAnimationActive={false} /></LineChart></ResponsiveContainer></div>
                <p className="muted mt-1 text-xs">Units: {obs.data.units}. Observation date ≠ publication date: latest observation {day(obs.data.observations.at(-1)?.observation_date)} was published {day(obs.data.observations.at(-1)?.published_date)} ({obs.data.observations.at(-1)?.pit_quality === "vintage" ? "official real-time vintage" : "publication date ASSUMED from a typical lag; add FRED_API_KEY for true vintages"}). {obs.data.note}</p>
              </>)}
          </Card>
        </div>)}
      <Card title={`Macro condition indicators — as of ${pil.data?.as_of ?? "…"}`}>
        {pil.isLoading ? <Loading /> : pil.error ? <ErrorState error={pil.error} /> : (
          <div className="space-y-4">{Object.entries(pil.data!.pillars).map(([k, p]) => (
            <div key={k}><div className="font-medium capitalize">{k}: <span className="num">{p.score === null ? "unavailable" : p.score.toFixed(2)}</span> <span className="muted text-sm font-normal">{p.label} — {p.title}</span></div>
              <table className="dt mt-1"><thead><tr><th>Input</th><th>Transform</th><th>Sign</th><th>Latest</th><th>z</th><th>Weight</th><th>Observed</th><th>Published</th><th>Status</th></tr></thead><tbody>
                {p.inputs.map((i) => (<tr key={i.series + i.description}><td>{i.description} <span className="muted">({i.series})</span></td><td>{i.transform ?? "—"}</td><td>{i.sign ?? "—"}</td><td className="num">{num(i.latest_transformed)}</td><td className="num">{num(i.z)}</td><td className="num">{i.weight ? i.weight.toFixed(2) : "—"}</td><td>{day(i.observation_date)}</td><td>{day(i.published_date)}</td><td className={i.status === "ok" ? "" : "text-amber-600"}>{i.status}</td></tr>))}
              </tbody></table></div>))}
            <details className="text-xs"><summary className="cursor-pointer">Formula, normalisation and missing-data treatment</summary><pre className="mt-2 whitespace-pre-wrap">{pil.data!.method}</pre></details>
            <p className="muted text-xs">Regime-conditional asset sensitivities (e.g. cuts due to easing inflation vs. recession) are not yet modelled; the only regime split currently reported is the trend regime in model performance.</p></div>)}
      </Card>
    </>
  );
}
