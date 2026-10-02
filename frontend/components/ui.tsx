"use client";
import { ApiError } from "@/lib/api";
import React from "react";

export const STATUS_TEXT: Record<string, { label: string; cls: string; help: string }> = {
  validated: { label: "Validated OOS", cls: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300", help: "Out-of-sample: beats the unconditional baseline, calibrated, stable across halves. Not a promise of future accuracy." },
  no_edge_over_baseline: { label: "No edge vs baseline", cls: "bg-amber-100 text-amber-900 dark:bg-amber-900/40 dark:text-amber-200", help: "Out-of-sample, the model did not beat simply using the historical base rate." },
  poorly_calibrated: { label: "Poorly calibrated", cls: "bg-amber-100 text-amber-900 dark:bg-amber-900/40 dark:text-amber-200", help: "Stated probabilities did not match realised frequencies." },
  unstable: { label: "Unstable", cls: "bg-amber-100 text-amber-900 dark:bg-amber-900/40 dark:text-amber-200", help: "Skill differed in sign between the first and second half of the test period." },
  insufficient_data: { label: "Insufficient data", cls: "bg-zinc-200 text-zinc-800 dark:bg-zinc-700 dark:text-zinc-200", help: "Too few out-of-sample observations to judge." },
  baseline: { label: "Baseline", cls: "bg-zinc-200 text-zinc-800 dark:bg-zinc-700 dark:text-zinc-200", help: "Historical-frequency reference model." },
};

export function StatusBadge({ s }: { s: string | null | undefined }) {
  if (!s) return <span className="muted">—</span>;
  const t = STATUS_TEXT[s] ?? { label: s, cls: "bg-zinc-200 text-zinc-800", help: "" };
  return <span title={t.help} className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${t.cls}`}>{t.label}</span>;
}

export function Loading({ what = "data" }: { what?: string }) {
  return <div className="muted p-6 text-sm" role="status">Loading {what}…</div>;
}

export function ErrorState({ error }: { error: unknown }) {
  const e = error as ApiError;
  return (
    <div className="panel border-red-400 p-4 text-sm" role="alert">
      <div className="font-semibold text-red-600">Could not load data</div>
      <div className="muted mt-1">{e?.message ?? "Unknown error"}{e?.code && e.code !== "network" ? ` (${e.code})` : ""}</div>
    </div>
  );
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <div className="panel muted p-6 text-sm">{children}</div>;
}

export function Card({ title, right, children, className = "" }: { title?: string; right?: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <section className={`panel ${className}`}>
      {title && <header className="flex items-center justify-between border-b px-4 py-2.5" style={{ borderColor: "var(--line)" }}><h2 className="text-sm font-semibold">{title}</h2>{right}</header>}
      <div className="p-4">{children}</div>
    </section>
  );
}

export function Stat({ label, value, sub, cls = "" }: { label: string; value: React.ReactNode; sub?: React.ReactNode; cls?: string }) {
  return <div><div className="muted text-xs">{label}</div><div className={`num text-lg font-semibold ${cls}`}>{value}</div>{sub && <div className="muted text-xs">{sub}</div>}</div>;
}

export const Disclaimer = () => (
  <p className="muted text-xs">Research and decision-support only. Forecasts are statistical model estimates, not facts, advice or guarantees; past out-of-sample behaviour may not persist.</p>
);
