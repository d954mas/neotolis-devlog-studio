// Client-side take model. The frozen API has no "list takes" endpoint — the
// upload returns only {path} — so recorded takes are tracked per-session here,
// keyed by beat. Playback uses a local object URL; processing uses serverPath.

export type UploadState = "uploading" | "uploaded" | "error";
export type ProcessState = "idle" | "running" | "done" | "error";

export interface VoiceTakeMetadata {
  schema: "devlog.voice_take";
  version: 1;
  countdown_seconds: number;
  room_tone_seconds: number;
  speech_start_seconds: number;
  stop_requested_seconds: number;
  post_roll_end_seconds: number;
  post_roll_target_seconds: number;
  post_roll_completed: boolean;
  completed_lead_in: boolean;
}

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
  metadataPath?: string;
  recordingMetadata?: VoiceTakeMetadata;
  processState: ProcessState;
  processMessage?: string;
  qualityStatus?: "clean" | "unverified" | "re_record";
  qualityMessage?: string;
  verdictPath?: string;
}

export function newTakeId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}
