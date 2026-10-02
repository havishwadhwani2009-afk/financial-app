"use client";
import { Card, Empty, ErrorState, Loading } from "@/components/ui";
import { get, Status } from "@/lib/api";
import { day, num, pct, spct, tone, ts } from "@/lib/format";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";

type Mkt = { symbol: string; id?: number; name: string | null; available: boolean; last?: number; date?: string; stale?: boolean; ret_1d?: number; ret_1m?: number; ret_1y?: number };
type Latest = { series_id: string; available: boolean; title?: string; units?: string; value?: number; observation_date?: string; first_published?: string };
type Pillars = { as_of: string; pillars: Record<string, { title: string; score: number | null; label: string | null; inputs: { series: string; status: string }[] }> };

export default function Overview() {
  const mk = useQuery({ queryKey: ["overview"], queryFn: () => get<{ markets: Mkt[]; note: string }>("/overview") });
  const mac = useQuery({ queryKey: ["macro-ov"], queryFn: () => get<Latest[]>("/macro/overview") });
  const pil = useQuery({ queryKey: ["pillars"], queryFn: () => get<Pillars>("/macro/pillars") });
  const st = useQuery({ queryKey: ["status"], queryFn: () => get<Status>("/status") });
  return (
    <>
      <h1 className="text-xl font-semibold">Global overview</h1>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Markets (latest stored close)">
          {mk.isLoading ? <Loading /> : mk.error ? <ErrorState error={mk.error} /> : mk.data!.markets.length === 0 ? <Empty>No instruments ingested yet.</Empty> : (
            <>
              <table className="dt"><thead><tr><th>Symbol</th><th>Name</th><th>Last</th><th>1D</th><th>1M</th><th>1Y</th><th>As of</th></tr></thead><tbody>
                {mk.data!.markets.map((m) => m.available ? (
                  <tr key={m.symbol}><td><Link className="lnk" href={`/assets/${m.id}`}>{m.symbol}</Link></td><td>{m.name}</td><td className="num">{num(m.last)}</td>
                    <td className={`num ${tone(m.ret_1d)}`}>{spct(m.ret_1d)}</td><td className={`num ${tone(m.ret_1m)}`}>{spct(m.ret_1m)}</td><td className={`num ${tone(m.ret_1y)}`}>{spct(m.ret_1y)}</td>
                    <td>{day(m.date)}{m.stale && <span className="ml-1 text-amber-600" title="Stale">⚠ stale</span>}</td></tr>
                ) : <tr key={m.symbol}><td>{m.symbol}</td><td colSpan={6} className="muted">no price data ingested</td></tr>)}
              </tbody></table>
              <p className="muted mt-2 text-xs">{mk.data!.note}</p>
            </>
          )}
        </Card>
        <Card title="Rates, dollar, credit, volatility (FRED)">
          {mac.isLoading ? <Loading /> : mac.error ? <ErrorState error={mac.error} /> : !mac.data!.some((x) => x.available) ? <Empty>No macro series ingested yet.</Empty> : (
            <table className="dt"><thead><tr><th>Series</th><th>Value</th><th>Observed</th><th>First published</th></tr></thead><tbody>
              {mac.data!.filter((x) => x.available).map((x) => (
                <tr key={x.series_id}><td title={x.title}>{x.title} <span className="muted">({x.series_id})</span></td><td className="num">{num(x.value)}</td><td>{day(x.observation_date)}</td><td>{day(x.first_published)}</td></tr>))}
            </tbody></table>)}
        </Card>
      </div>
      <Card title="Macro condition indicators (z-scores vs trailing 10 years, point-in-time)" right={<Link className="lnk text-xs" href="/macro">Formula & detail →</Link>}>
        {pil.isLoading ? <Loading /> : pil.error ? <ErrorState error={pil.error} /> : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {Object.entries(pil.data!.pillars).map(([k, p]) => (
              <div key={k} className="panel p-3"><div className="text-xs font-semibold capitalize">{k}</div><div className="muted text-xs">{p.title}</div>
                <div className="num mt-1 text-lg font-semibold">{p.score === null ? "unavailable" : `${p.score >= 0 ? "+" : ""}${p.score.toFixed(2)}`} <span className="muted text-xs font-normal">{p.label}</span></div>
                <div className="muted text-xs">{p.inputs.filter((i) => i.status === "ok").length}/{p.inputs.length} inputs available</div></div>))}
          </div>)}
        <p className="muted mt-3 text-xs">Descriptive conditions only; no market-impact is assumed. Market breadth and economic release calendar are not available from the integrated free sources.</p>
      </Card>
      <Card title="Data sources & freshness">
        {st.isLoading ? <Loading /> : st.error ? <ErrorState error={st.error} /> : st.data!.providers.length === 0 ? <Empty>No ingestion has run yet. See README → “Load data”.</Empty> : (
          <table className="dt"><thead><tr><th>Provider</th><th>Last status</th><th>Last success</th><th>OK / failed (24h)</th><th>Last error</th></tr></thead><tbody>
            {st.data!.providers.map((p) => (<tr key={p.provider}><td>{p.provider}</td><td className={p.last_run_status === "failed" ? "text-red-600" : ""}>{p.last_run_status}</td><td>{ts(p.last_success)}</td><td className="num">{p.successes_24h} / {p.failures_24h}</td><td className="muted">{p.last_error ?? ""}</td></tr>))}
          </tbody></table>)}
        {st.data && <p className="muted mt-2 text-xs">Latest price date {day(st.data.latest_price_date)} · latest macro observation {day(st.data.latest_macro_observation)} · {st.data.counts.instruments_with_prices}/{st.data.counts.instruments} instruments with prices</p>}
      </Card>
    </>
  );
}
