export type RiskTier = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";

export interface ConformalInterval {
  lower: number;
  upper: number;
  confidence_level: number;
}

export interface SignalAttribution {
  rav: number;
  scs: number;
  nli: number;
  ics: number;
  vgs?: number | null;
}

export interface ClaimItem {
  claim_id: string;
  text: string;
  type: string;
  criticality: string;
  status: string;
  hrs_contribution: number;
}

export interface VerificationSession {
  session_id: string;
  tenant_id: string;
  trace_id: string;
  model_id: string;
  timestamp: string;
  prompt: string;
  response: string;
  hrs_score: number;
  risk_tier: RiskTier;
  ci_lower: number;
  ci_upper: number;
  correction_applied: boolean;
  claims_count: number;
  contradicted_count: number;
  claims: ClaimItem[];
  signal_attribution: SignalAttribution;
}

export interface DashboardStats {
  tenant_id: string;
  total_verifications: number;
  average_hrs: number;
  tier_distribution: Record<RiskTier, number>;
  correction_rate: number;
  critical_rate: number;
  drift_alert: boolean;
}

export interface CircuitInfo {
  state: "closed" | "open" | "half-open";
  fail_counter: number;
  fail_max: number;
  reset_timeout: number;
}

export interface DriftTimeSeriesPoint {
  date: string;
  mean_hrs: number;
  sample_count: number;
  critical_count: number;
}

export interface DriftReport {
  psi: number;
  psi_status: "STABLE" | "MODERATE_DRIFT" | "SIGNIFICANT_DRIFT";
  ks_p_value: number;
  rolling_mean_increase: number;
  alert: boolean;
  timeseries: DriftTimeSeriesPoint[];
}
