export type EngineT = {
  id: number; name: string; provider: string; provider_label: string; model: string; base_url: string;
  local: boolean; has_key: boolean; key_hint: string; price_in: number | null; price_out: number | null;
  monthly_limit_usd: number | null; effective_limit_usd: number | null; spent_usd: number; enabled: boolean;
  agreement: number | null; decisions: number; options: Record<string, unknown>;
};
export type EngineSettings = {
  mode: "single" | "multi"; default_engine_id: number | null; task_engines: Record<string, number>;
  multi_engine_ids: number[]; merge_engine_id: number | null; default_limit_usd: number;
};
export type Accuracy = { engine: string; task: string; task_name: string; agree: number; total: number; rate: number | null };
export type EnginesPayload = { engines: EngineT[]; settings: EngineSettings; accuracy: Accuracy[] };

export type Verdict = { label: string; evidence: string; reasoning: string; items: { type: string; value: string }[] };
export type Claims = { claims: { text: string; speaker: string; type: string }[] };
export type Summary = { summary: string; points: string[] };
export type Output = Partial<Verdict & Claims & Summary>;

export type Run = {
  id: number; engine_id: number | null; engine: string; status: "ok" | "error" | "invalid" | "limit"; error: string;
  output: Output | null; model: string; model_version: string; prompt: string; input_tokens: number; output_tokens: number;
  cost_usd: number | null; duration_ms: number;
};
export type Merge = {
  id: number; engine: string; status: string; error: string; cost_usd: number | null; created_at: string;
  output: { final: Output; attribution: { point: string; engines: string[] }[];
    disagreements: { topic: string; positions: Record<string, string>; suggested: string; why: string }[] } | null;
};
export type Item = { text: string; engines: string[]; agreed: boolean; share: string; data: Record<string, string> };
export type Batch = {
  id: number; task: string; task_name: string; input: { claim?: string; text?: string }; mode: string;
  status: "pending" | "running" | "done"; created_at: string; runs: Run[]; merges: Merge[];
  comparison: { engines: number; succeeded: number; votes?: Record<string, number>; agreement?: number;
    suggested?: string | null; evidence?: Record<string, string>; unanimous?: boolean;
    disagreement?: "none" | "minor" | "major"; items?: Item[] };
  total_cost_usd: number;
  decision: { output: Output; source: string; note: string; decided_by: number; decided_at: string } | null;
};

export const money = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `${v.toFixed(v < 1 ? 3 : 2)} $`);
export const pct = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `${Math.round(v * 100)}٪`);
