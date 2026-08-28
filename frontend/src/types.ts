export type AnalysisStatus = "queued" | "running" | "completed" | "failed";
export type FeedbackAccuracy = "accurate" | "partial" | "inaccurate";

export interface CurrentUser {
  github_user_id: number;
  login: string;
  avatar_url: string | null;
  installations: {
    installation_id: number;
    account_login: string;
    account_type: string;
    repository_selection: string;
  }[];
}

export interface Evidence {
  source: string;
  content: string;
  location: string | null;
}

export interface Suggestion {
  description: string;
  file: string | null;
  patch: string | null;
}

export interface Feedback {
  run_id: number;
  accuracy: FeedbackAccuracy | null;
  suggestion_resolved: boolean | null;
  comment: string | null;
  created_at: string;
  updated_at: string;
}

export interface Analysis {
  run_id: number;
  repository: string;
  workflow_name: string;
  head_sha: string;
  html_url: string;
  trust_level: "trusted" | "untrusted_fork";
  status: AnalysisStatus;
  classification: {
    category: string;
    confidence: number;
    first_error: string;
    related_step: string | null;
    matched_rules: string[];
  } | null;
  diagnosis: {
    summary: string;
    root_cause: string;
    confidence: number;
    evidence: Evidence[];
    suggestions: Suggestion[];
    conflicts: string[];
    notes: string[];
  } | null;
  related_files: {
    filename: string;
    score: number;
    reasons: string[];
    patch_excerpt: string | null;
  }[];
  workflow_path: string | null;
  model_name: string | null;
  prompt_version: string | null;
  feedback: Feedback | null;
  error: string | null;
  created_at: string;
  updated_at: string;
}
