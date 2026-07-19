export type ResearchWindow = "7d" | "30d" | "90d" | "all";
export type ResearchSort = "outlier" | "velocity" | "views" | "newest";
export type ExperimentMode = "inspiration" | "adaptation" | "remake";
export type ExperimentVerdict = "worked" | "mixed" | "did_not_work" | "inconclusive";

export interface ExperimentResult {
  verdict: ExperimentVerdict;
  published_url: string;
  views: number;
  likes: number;
  comments: number;
  notes: string;
  measured_at: string;
}

export interface ResearchProjectSummary {
  id: string;
  title: string;
  description: string;
  author_count: number;
  reel_count: number;
  experiment_count: number;
  agent_brief_path: string;
}

export interface ResearchProjectCreated {
  id: string;
  title: string;
  description: string;
  style_profile: string;
}

export interface ResearchAuthor {
  id: string;
  username: string;
  display_name: string;
  profile_url: string;
  followers_count: number | null;
  median_views: number | null;
}

export interface ResearchExperiment {
  id: string;
  reel_id: string;
  mode: ExperimentMode;
  status: "idea" | "draft" | "published" | "measured";
  hypothesis: string;
  take_from_reference: string[];
  keep_original: string[];
  created_at: string;
  agent_context_path: string;
  result?: ExperimentResult | null;
}

export interface ResearchReel {
  id: string;
  author_id: string;
  platform: string;
  url: string;
  caption: string;
  thumbnail_url: string;
  published_at: string;
  duration_seconds: number | null;
  views: number;
  likes: number;
  comments: number;
  metrics_captured_at: string;
  metrics_history: Array<{ captured_at: string; views: number; likes: number; comments: number }>;
  hook: string;
  patterns: string[];
  author: ResearchAuthor;
  age_hours: number;
  metrics_age_hours: number;
  views_per_hour: number;
  growth_views: number | null;
  growth_hours: number | null;
  growth_per_hour: number | null;
  velocity: number;
  outlier_score: number | null;
  experiment: ResearchExperiment | null;
}

export interface ResearchProjectFeed {
  id: string;
  title: string;
  description: string;
  style_profile: string;
  window: ResearchWindow;
  sort: ResearchSort;
  authors: ResearchAuthor[];
  reels: ResearchReel[];
  experiments: ResearchExperiment[];
  agent_brief_path: string;
}

export interface ResearchCollectorStatus {
  provider: "scrapecreators";
  configured: boolean;
  max_authors_per_sync: number;
  credits_per_author: number;
  max_credits_per_author: number;
  free_credits: number;
  paid_price_per_1000_requests_usd: number;
  max_paid_cost_per_sync_usd: number;
}

export interface ResearchSyncResult {
  provider: "scrapecreators";
  authors_requested: number;
  authors_completed: number;
  credits_used: number;
  max_credits: number;
  credits_remaining: number | null;
  items_received: number;
  reels_imported: number;
  items_skipped: number;
  failures: Array<{ author_id: string; error: string }>;
  captured_at: string;
}

interface ProjectInput {
  title: string;
  description: string;
  style_profile: string;
}

interface AuthorInput {
  username: string;
  display_name?: string;
  followers_count?: number | null;
  median_views?: number | null;
}

export interface ReelInput {
  id: string;
  author_id: string;
  url: string;
  published_at: string;
  views: number;
  likes?: number;
  comments?: number;
  caption?: string;
  hook?: string;
  patterns?: string[];
  thumbnail_url?: string;
  platform?: string;
}

export interface ExperimentInput {
  reel_id: string;
  mode: ExperimentMode;
  hypothesis: string;
  take_from_reference: string[];
  keep_original: string[];
}

export interface ExperimentResultInput {
  verdict: ExperimentVerdict;
  published_url: string;
  views: number;
  likes: number;
  comments: number;
  notes: string;
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    headers: { Accept: "application/json", ...(init?.headers || {}) },
    ...init,
  });
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (payload.detail) detail = payload.detail;
    } catch {
      // Keep the status fallback for non-JSON errors.
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

function post<T>(url: string, body: unknown): Promise<T> {
  return request<T>(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export const researchApi = {
  projects: () => request<ResearchProjectSummary[]>("/api/research/projects"),
  collectorStatus: () => request<ResearchCollectorStatus>("/api/research/collector/status"),
  createProject: (body: ProjectInput) =>
    post<ResearchProjectCreated>("/api/research/projects", body),
  project: (
    projectId: string,
    window: ResearchWindow,
    sort: ResearchSort,
    authorId: string | null,
  ) => {
    const query = new URLSearchParams({ range: window, sort });
    if (authorId) query.set("author_id", authorId);
    return request<ResearchProjectFeed>(
      `/api/research/projects/${encodeURIComponent(projectId)}?${query}`,
    );
  },
  addAuthor: (projectId: string, body: AuthorInput) =>
    post<ResearchAuthor>(
      `/api/research/projects/${encodeURIComponent(projectId)}/authors`,
      body,
    ),
  addReel: (projectId: string, body: ReelInput) =>
    post<ResearchReel>(
      `/api/research/projects/${encodeURIComponent(projectId)}/reels`,
      body,
    ),
  syncProject: (projectId: string, authorIds?: string[]) =>
    post<ResearchSyncResult>(
      `/api/research/projects/${encodeURIComponent(projectId)}/sync`,
      { author_ids: authorIds },
    ),
  createExperiment: (projectId: string, body: ExperimentInput) =>
    post<ResearchExperiment>(
      `/api/research/projects/${encodeURIComponent(projectId)}/experiments`,
      body,
    ),
  recordExperimentResult: (
    projectId: string,
    experimentId: string,
    body: ExperimentResultInput,
  ) => post<ResearchExperiment>(
    `/api/research/projects/${encodeURIComponent(projectId)}/experiments/${encodeURIComponent(experimentId)}/result`,
    body,
  ),
};
