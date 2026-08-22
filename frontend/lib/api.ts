/**
 * Typed client for the SplitShield backend API.
 *
 * The backend origin comes from NEXT_PUBLIC_API_URL (defaults to same-origin
 * `/api` behind the dev proxy or Docker Compose nginx-less setup).
 */

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    public status: number,
    detail: string,
  ) {
    super(detail);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`;
    try {
      const body = (await resp.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(resp.status, detail);
  }
  return (await resp.json()) as T;
}

// ---------------------------------------------------------------------------
// Types mirrored from the backend
// ---------------------------------------------------------------------------

export interface AuditConfig {
  enable_exact: boolean;
  enable_perceptual: boolean;
  enable_semantic: boolean;
  phash_threshold: number | null;
  phash_strong_threshold: number | null;
  semantic_threshold: number | null;
  semantic_top_k: number | null;
  run_evaluation: boolean;
}

export const defaultConfig: AuditConfig = {
  enable_exact: true,
  enable_perceptual: true,
  enable_semantic: true,
  phash_threshold: null,
  phash_strong_threshold: null,
  semantic_threshold: null,
  semantic_top_k: null,
  run_evaluation: true,
};

export interface JobCreated {
  job_id: string;
  status: string;
}

export interface StageInfo {
  key: string;
  label: string;
  state: "complete" | "active" | "pending";
}

export interface JobStatus {
  job_id: string;
  status: "queued" | "running" | "complete" | "failed" | "deleted";
  stage: string;
  stage_label: string;
  stages: StageInfo[];
  progress: number;
  message: string | null;
  error: string | null;
  source: string;
  dataset_name: string | null;
  created_at: string;
  expires_at: string;
}

export interface ScoreComponent {
  category: string;
  weight: number;
  affected_samples: number;
  rate: number;
  saturation: number | null;
  penalty: number;
  explanation: string;
}

export interface Integrity {
  score: number;
  grade: string;
  total_penalty: number;
  total_valid_samples: number;
  components: ScoreComponent[];
  formula: string;
}

export interface EvalBlock {
  test_samples: number;
  accuracy: number;
  macro_f1: number;
  accuracy_ci95: { low: number; high: number; iterations: number } | null;
}

export interface Evaluation {
  eligible: boolean;
  reason: string;
  model?: string;
  seed?: number;
  classes?: string[];
  train_samples?: number;
  original?: EvalBlock;
  cleaned?: EvalBlock | null;
  quarantined_test_samples?: number;
  quarantine_reasons?: string[];
  observed_evaluation_gap?: number | null;
  note?: string;
  warnings: string[];
}

export interface Inventory {
  total_samples: number;
  total_valid_samples: number;
  total_corrupt_samples: number;
  rejected_count: number;
  rejected_files: { path: string; reason: string }[];
  per_split: Record<string, number>;
  per_class_total: Record<string, number>;
  per_split_class: Record<string, Record<string, number>>;
  classes: string[];
  class_count: number;
  missing_class_in_split: { split: string; label: string }[];
  class_imbalance_ratio: number | null;
  test_fraction: number;
  dimensions: Record<string, Record<string, number>>;
  formats: Record<string, number>;
  corrupt_samples: { id: string; split: string; label: string; error: string }[];
}

export interface Summary {
  inventory: Inventory;
  integrity: Integrity;
  config: Record<string, unknown>;
  backend_note: string;
  embedding_backend: {
    key: string;
    name: string;
    kind: string;
    dim: number;
    description: string;
    semantic_claim: string;
  } | null;
  counts: {
    findings_total: number;
    exact_cross_split: number;
    near_cross_split: number;
    semantic_overlap: number;
    conflicting_label: number;
    same_split_redundancy: number;
    corrupt: number;
  };
  severity_counts: Record<string, number>;
  review_counts: { confirmed: number; safe: number; uncertain: number };
  evaluation: Evaluation | null;
  fingerprint: string | null;
  dataset_issues: {
    id: string;
    kind: string;
    severity: string;
    title: string;
    detail: Record<string, unknown>;
  }[];
}

export interface SampleRef {
  id: string;
  split?: string;
  label?: string;
  width?: number | null;
  height?: number | null;
  bytes?: number | null;
  corrupt?: boolean;
}

export interface Finding {
  id: string;
  kind: string;
  severity: "critical" | "high" | "medium" | "low" | "info";
  confidence_label: string;
  method: string;
  distance: number;
  similarity: number;
  cross_split: boolean;
  conflicting_label: boolean;
  group_id: string | null;
  detail: { methods?: string[]; corroborated_by_multiple_methods?: boolean };
  sample_a: SampleRef;
  sample_b: SampleRef;
  split_a: string;
  split_b: string;
  class_a: string;
  class_b: string;
  review: { decision: string; note: string | null };
}

export interface FindingsPage {
  total: number;
  page: number;
  page_size: number;
  items: Finding[];
}

export interface RepairEntry {
  sample_id: string;
  rel_path: string;
  original_split: string;
  proposed_split: string;
  label: string;
  group_id: string | null;
  action: "keep" | "move" | "exclude";
  reason: string;
}

export interface RepairPlan {
  entries: RepairEntry[];
  groups: {
    group_id: string;
    members: string[];
    splits: Record<string, number>;
    labels: string[];
    resolution: string;
    reason: string;
  }[];
  moves: number;
  exclusions: number;
  before_counts: Record<string, number>;
  after_counts: Record<string, number>;
  warnings: string[];
}

export interface Capabilities {
  version: string;
  embedding_backend: {
    key: string;
    name: string;
    kind: string;
    dim: number;
    description: string;
    semantic_claim: string;
  } | null;
  embedding_note: string;
  video_support: boolean;
  limits: {
    max_upload_bytes: number;
    max_file_count: number;
    max_uncompressed_bytes: number;
    retention_hours: number;
  };
  defaults: {
    phash_threshold: number;
    phash_strong_threshold: number;
    semantic_threshold: number;
    semantic_top_k: number;
  };
}

// ---------------------------------------------------------------------------
// Calls
// ---------------------------------------------------------------------------

export const api = {
  health: () => request<{ status: string; version: string }>("/api/health"),
  capabilities: () => request<Capabilities>("/api/capabilities"),

  createDemoAudit: (config: Partial<AuditConfig>) =>
    request<JobCreated>("/api/audits/demo", {
      method: "POST",
      body: JSON.stringify(config),
    }),

  uploadAudit: async (file: File, config: Partial<AuditConfig>): Promise<JobCreated> => {
    const form = new FormData();
    form.append("file", file);
    const params = new URLSearchParams({ config: JSON.stringify(config) });
    const resp = await fetch(`${API_BASE}/api/audits/upload?${params}`, {
      method: "POST",
      body: form,
    });
    if (!resp.ok) {
      let detail = `HTTP ${resp.status}`;
      try {
        const body = (await resp.json()) as { detail?: unknown };
        if (typeof body.detail === "string") detail = body.detail;
      } catch {
        /* ignore */
      }
      throw new ApiError(resp.status, detail);
    }
    return (await resp.json()) as JobCreated;
  },

  jobStatus: (jobId: string) => request<JobStatus>(`/api/audits/${jobId}`),
  summary: (jobId: string) => request<Summary>(`/api/audits/${jobId}/summary`),

  findings: (jobId: string, params: Record<string, string | number>) => {
    const search = new URLSearchParams(
      Object.entries(params).map(([k, v]) => [k, String(v)]),
    );
    return request<FindingsPage>(`/api/audits/${jobId}/findings?${search}`);
  },

  review: (jobId: string, findingId: string, decision: string, note?: string) =>
    request<{ finding_id: string; decision: string }>(
      `/api/audits/${jobId}/findings/${findingId}/review`,
      { method: "PATCH", body: JSON.stringify({ decision, note: note ?? null }) },
    ),

  repair: (jobId: string) => request<RepairPlan>(`/api/audits/${jobId}/repair`),
  regenerateRepair: (jobId: string, includeSemantic: boolean) =>
    request<RepairPlan>(`/api/audits/${jobId}/repair`, {
      method: "POST",
      body: JSON.stringify({ include_semantic: includeSemantic }),
    }),

  rerunEvaluation: (jobId: string) =>
    request<Evaluation>(`/api/audits/${jobId}/evaluation/rerun`, { method: "POST" }),

  deleteAudit: (jobId: string) =>
    request<{ deleted: string }>(`/api/audits/${jobId}`, { method: "DELETE" }),

  imageUrl: (jobId: string, sampleId: string) =>
    `${API_BASE}/api/audits/${jobId}/images/${sampleId}`,
  findingsCsvUrl: (jobId: string) => `${API_BASE}/api/audits/${jobId}/findings.csv`,
  repairCsvUrl: (jobId: string) => `${API_BASE}/api/audits/${jobId}/repair.csv`,
  repairJsonUrl: (jobId: string) => `${API_BASE}/api/audits/${jobId}/repair.json`,
  reportJsonUrl: (jobId: string) => `${API_BASE}/api/audits/${jobId}/report.json`,
  reportHtmlUrl: (jobId: string) => `${API_BASE}/api/audits/${jobId}/report.html`,
};
