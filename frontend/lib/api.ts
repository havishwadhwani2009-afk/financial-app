export const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api";

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) { super(message); }
}

export async function get<T>(path: string, params?: Record<string, string | number | boolean | undefined | null>): Promise<T> {
  const qs = params ? "?" + new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "").map(([k, v]) => [k, String(v)])).toString() : "";
  let res: Response;
  try { res = await fetch(`${API}${path}${qs}`); }
  catch { throw new ApiError(0, "network", `Cannot reach the API at ${API}. Is the backend running?`); }
  if (!res.ok) {
    let code = "http_error", message = res.statusText;
    try { const j = await res.json(); code = j.error?.code ?? code; message = j.error?.message ?? message; } catch {}
    throw new ApiError(res.status, code, message);
  }
  return res.json();
}

export type Page<T> = { items: T[]; total: number; limit: number; offset: number };
export type Asset = { id: number; symbol: string; exchange: string; name: string | null; instrument_type: string; currency: string | null; country: string | null; sector: string | null; industry: string | null; cik: string | null; metadata_source: string | null };
export type Evidence = { feature: string; value: number | null; z: number | null; contribution: number | null; importance?: number };
export type Forecast = {
  id: number; instrument_id: number; symbol: string | null; horizon_days: number; horizon_label: string; model_name: string; model_version: string;
  feature_version: string; created_at: string; data_cutoff: string; expected_return: number | null; prob_up: number | null; prob_down: number | null;
  interval_low: number | null; interval_high: number | null; interval_level: number | null; interval_method: string | null;
  hist_vol_ann: number | null; est_vol_ann: number | null; validation_status: string;
  evidence: { bullish: Evidence[]; bearish: Evidence[]; limitations: string[]; invalidating_conditions: string[]; validation_reasons: string[]; backtest: Record<string, number | string | null> } | null;
};
export type ScreenerRow = {
  id: number; symbol: string; name: string | null; instrument_type: string; sector: string | null; price: number | null; price_date: string | null;
  ret_1d: number | null; ret_1m: number | null; ret_3m: number | null; ret_1y: number | null; pe: number | null; ps: number | null;
  revenue_growth: number | null; net_income_growth: number | null; forecast_horizon_days: number; forecast_id: number | null;
  prob_up: number | null; expected_return: number | null; interval_low: number | null; interval_high: number | null; validation_status: string | null; data_cutoff: string | null;
};
export type Status = {
  providers: { provider: string; last_success: string | null; last_run_status: string; last_error: string | null; failures_24h: number; successes_24h: number }[];
  counts: Record<string, number>; latest_price_date: string | null; latest_macro_observation: string | null; prices_stale: boolean; empty: boolean; message: string | null;
};
export type PriceSeries = { instrument_id: number; symbol: string; count: number; last_date: string | null; last_ingested_at: string | null; stale: boolean; prices: { date: string; close: number; adj_close: number | null; volume: number | null; provider: string }[] };
export type Backtest = {
  id: number; instrument_id: number; symbol: string; model_name: string; model_version: string; horizon_days: number; created_at: string; data_cutoff: string;
  n_obs: number; start_date: string | null; end_date: string | null; validation_status: string; validation_reasons: string[] | null;
  brier: number | null; brier_baseline: number | null; brier_skill: number | null; log_loss: number | null; ece: number | null;
  balanced_accuracy: number | null; directional_accuracy: number | null; mae: number | null; mae_baseline: number | null; rmse: number | null;
};
