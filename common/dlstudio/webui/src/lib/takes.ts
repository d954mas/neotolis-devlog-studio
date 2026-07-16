// Client-side take model. The frozen API has no "list takes" endpoint — the
// upload returns only {path} — so recorded takes are tracked per-session here,
// keyed by beat. Playback uses a local object URL; processing uses serverPath.

export type UploadState = "uploading" | "uploaded" | "error";
export type ProcessState = "idle" | "running" | "done" | "error";

export interface SessionTake {
  id: string;
  beatId: string;
  filename: string;
  url: string; // local object URL for immediate playback
  size: number;
  createdAt: number;
  uploadState: UploadState;
  uploadError?: string;
  serverPath?: string;
  processState: ProcessState;
  processMessage?: string;
}

export function newTakeId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}
