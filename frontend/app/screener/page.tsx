"use client";
import { Card, Empty, ErrorState, Loading, StatusBadge } from "@/components/ui";
import { get, Page, ScreenerRow } from "@/lib/api";
import { day, num, pct, spct, tone } from "@/lib/format";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

const HORIZONS: [number, string][] = [[5, "1 week"], [21, "1 month"], [63, "3 months"], [126, "6 months"], [252, "12 months"]];
const COLS: [keyof ScreenerRow, string][] = [["symbol", "Ticker"], ["name", "Name"], ["instrument_type", "Type"], ["sector", "Sector"], ["price", "Price"], ["ret_1d", "1D"], ["ret_1m", "1M"], ["ret_1y", "1Y"], ["pe", "P/E"], ["ps", "P/S"], ["revenue_growth", "Rev gr."], ["net_income_growth", "NI gr."], ["prob_up", "P(up)"], ["expected_return", "Exp. ret."]];

export default function Screener() {
  const [q, setQ] = useState(""); const [type, setType] = useState(""); const [horizon, setHorizon] = useState(21);
  const [sort, setSort] = useState<keyof ScreenerRow>("symbol"); const [order, setOrder] = useState<"asc" | "desc">("asc");
  const { data, error, isLoading } = useQuery({ queryKey: ["screener", q, type, horizon, sort, order], queryFn: () => get<Page<ScreenerRow>>("/screener", { q, type, horizon, sort, order, limit: 300 }) });
  const th = (k: keyof ScreenerRow, l: string) => (
    <th key={k} aria-sort={sort === k ? (order === "asc" ? "ascending" : "descending") : "none"}>
      <button onClick={() => { if (sort === k) setOrder(order === "asc" ? "desc" : "asc"); else { setSort(k); setOrder("asc"); } }}>{l}{sort === k ? (order === "asc" ? " ▲" : " ▼") : ""}</button></th>);
  return (
    <>
      <h1 className="text-xl font-semibold">Asset screener</h1>
      <Card>
        <div className="flex flex-wrap items-center gap-3">
          <input aria-label="Search" placeholder="Search ticker or name" value={q} onChange={(e) => setQ(e.target.value)} />
          <select aria-label="Instrument type" value={type} onChange={(e) => setType(e.target.value)}><option value="">All types</option><option value="stock">Stocks</option><option value="etf">ETFs</option></select>
          <div className="flex gap-1" role="group" aria-label="Forecast horizon">{HORIZONS.map(([h, l]) => <button key={h} className="btn" aria-pressed={horizon === h} onClick={() => setHorizon(h)}>{l}</button>)}</div>
        </div>
        <p className="muted mt-2 text-xs">Sorting by forecast columns is a convenience, not a ranking of suitability. A high P(up) with a weak validation status carries little information. Fundamental figures are the latest <i>annual</i> SEC filing.</p>
      </Card>
      {isLoading ? <Loading what="screener" /> : error ? <ErrorState error={error} /> : data!.items.length === 0 ? <Empty>No instruments match, or nothing has been ingested yet.</Empty> : (
        <div className="panel overflow-auto"><table className="dt"><thead><tr>{COLS.map(([k, l]) => th(k, l))}<th>Interval</th><th>Validation</th><th>Data cutoff</th><th>Price date</th></tr></thead><tbody>
          {data!.items.map((r) => (
            <tr key={r.id}>
              <td><Link className="lnk font-medium" href={`/assets/${r.id}`}>{r.symbol}</Link></td><td className="max-w-[220px] truncate" title={r.name ?? ""}>{r.name ?? "—"}</td><td>{r.instrument_type}</td><td className="max-w-[160px] truncate">{r.sector ?? "—"}</td>
              <td className="num">{num(r.price)}</td>
              <td className={`num ${tone(r.ret_1d)}`}>{spct(r.ret_1d)}</td><td className={`num ${tone(r.ret_1m)}`}>{spct(r.ret_1m)}</td><td className={`num ${tone(r.ret_1y)}`}>{spct(r.ret_1y)}</td>
              <td className="num">{num(r.pe, 1)}</td><td className="num">{num(r.ps, 1)}</td><td className={`num ${tone(r.revenue_growth)}`}>{spct(r.revenue_growth)}</td><td className={`num ${tone(r.net_income_growth)}`}>{spct(r.net_income_growth)}</td>
              <td className="num">{pct(r.prob_up, 0)}</td><td className={`num ${tone(r.expected_return)}`}>{spct(r.expected_return)}</td>
              <td className="num muted">{r.interval_low === null ? "—" : `${spct(r.interval_low, 0)} … ${spct(r.interval_high, 0)}`}</td>
              <td><StatusBadge s={r.validation_status} /></td><td>{day(r.data_cutoff)}</td><td>{day(r.price_date)}</td>
            </tr>))}
        </tbody></table></div>)}
      {data && <p className="muted text-xs">{data.total} instruments · horizon {HORIZONS.find(([h]) => h === horizon)![1]} ({horizon} trading days). “—” means the figure is unavailable, not zero.</p>}
    </>
  );
}
