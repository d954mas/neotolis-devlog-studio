// Thin, typed fetch wrappers over the frozen Studio v2 API.
import type {
  CheckReport,
  Feedback,
  JobHandle,
  JobStatus,
  Project,
  ProcessTakeRequest,
  RenderBeatRequest,
  TakeUploadResult,
  Timeline,
} from "./types";

async function getJSON<T>(url: string): Promise<T> {
  const r = await fetch(url, { headers: { Accept: "application/json" } });
  if (!r.ok) throw new Error(`GET ${url} → HTTP ${r.status}`);
  return (await r.json()) as T;
}

async function postJSON<T>(url: string, body: unknown): Promise<T> {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`POST ${url} → HTTP ${r.status}`);
  return (await r.json()) as T;
}

const sleep = (ms: number) => new Promise((res) => setTimeout(res, ms));

export const api = {
  project: () => getJSON<Project>("/api/project"),
  ir: () => getJSON<Timeline>("/api/ir"),
  check: () => getJSON<CheckReport>("/api/check"),
  feedback: () => getJSON<Feedback>("/api/feedback"),

  postFeedback: (patch: Partial<Feedback>) =>
    postJSON<Feedback>("/api/feedback", patch),

  /** Upload a recorded take blob for a beat (multipart field "file"). */
  async uploadTake(
    beatId: string,
    file: Blob,
    filename: string,
  ): Promise<TakeUploadResult> {
    const fd = new FormData();
    fd.append("file", file, filename);
    const r = await fetch(`/api/takes/${encodeURIComponent(beatId)}`, {
      method: "POST",
      body: fd,
    });
    if (!r.ok) throw new Error(`POST /api/takes/${beatId} → HTTP ${r.status}`);
    return (await r.json()) as TakeUploadResult;
  },

  processTake: (req: ProcessTakeRequest) =>
    postJSON<JobHandle>("/api/actions/process-take", req),

  renderBeat: (req: RenderBeatRequest) =>
    postJSON<JobHandle>("/api/actions/render-beat", req),

  job: (id: string) =>
    getJSON<JobStatus>(`/api/jobs/${encodeURIComponent(id)}`),

  /** URL to stream a project file (audio/video preview src). */
  fileUrl: (path: string) => `/api/file?path=${encodeURIComponent(path)}`,
};

export interface PollOptions {
  intervalMs?: number;
  onStatus?: (s: JobStatus) => void;
  signal?: AbortSignal;
}

/** Poll a job to completion. Resolves with the terminal JobStatus. */
export async function pollJob(
  jobId: string,
  opts: PollOptions = {},
): Promise<JobStatus> {
  const interval = opts.intervalMs ?? 1000;
  for (;;) {
    if (opts.signal?.aborted) throw new Error("polling aborted");
    const s = await api.job(jobId);
    opts.onStatus?.(s);
    if (s.status !== "running") return s;
    await sleep(interval);
  }
}
