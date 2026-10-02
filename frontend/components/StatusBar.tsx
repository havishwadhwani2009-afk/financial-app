"use client";
import { get, Status } from "@/lib/api";
import { day, ts } from "@/lib/format";
import { useQuery } from "@tanstack/react-query";

export function StatusBar() {
  const { data, error } = useQuery({ queryKey: ["status"], queryFn: () => get<Status>("/status"), refetchInterval: 60_000 });
  if (error) return <Banner kind="error">API unreachable — {(error as Error).message}</Banner>;
  if (!data) return null;
  if (data.empty) return <Banner kind="warn">{data.message} No data is displayed until real provider data has been ingested.</Banner>;
  const failing = data.providers.filter((p) => p.last_run_status === "failed");
  return (
    <>
      {data.prices_stale && <Banner kind="warn">Market data is stale: latest price date {day(data.latest_price_date)}.</Banner>}
      {failing.map((p) => <Banner key={p.provider} kind="warn">Provider <b>{p.provider}</b>: last run failed ({p.failures_24h} failures in 24h) — {p.last_error}. Last success: {ts(p.last_success)}.</Banner>)}
    </>
  );
}

function Banner({ kind, children }: { kind: "warn" | "error"; children: React.ReactNode }) {
  const c = kind === "error" ? "bg-red-100 text-red-900 dark:bg-red-950 dark:text-red-200" : "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200";
  return <div role="alert" className={`${c} px-4 py-2 text-xs`}>{children}</div>;
}
