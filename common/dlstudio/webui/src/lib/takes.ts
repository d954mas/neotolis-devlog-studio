// Client-side take model. Uploaded takes are persisted in localStorage so a
// page reload does not lose the server path or an in-flight processing job.
// Raw, not-yet-uploaded blobs deliberately remain session-only.

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
  processJobId?: string;
  qualityStatus?: "clean" | "unverified" | "re_record";
  qualityMessage?: string;
  verdictPath?: string;
}

export function newTakeId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export type TakesByBeat = Record<string, SessionTake[]>;

const STORAGE_VERSION = 1;

export function takesStorageKey(editName: string): string {
  return `dlstudio:${editName}:uploaded-takes:v${STORAGE_VERSION}`;
}

export function serializeUploadedTakes(takes: TakesByBeat): string {
  const persisted: TakesByBeat = {};
  for (const [beatId, list] of Object.entries(takes)) {
    const uploaded = list
      .filter((take) => take.uploadState === "uploaded" && take.serverPath)
      .map((take) => ({ ...take, url: "" }));
    if (uploaded.length) persisted[beatId] = uploaded;
  }
  return JSON.stringify({ version: STORAGE_VERSION, takes: persisted });
}

export function restoreUploadedTakes(
  raw: string | null,
  fileUrl: (path: string) => string,
): TakesByBeat {
  if (!raw) return {};
  try {
    const parsed = JSON.parse(raw) as {
      version?: unknown;
      takes?: unknown;
    };
    if (parsed.version !== STORAGE_VERSION || !parsed.takes || typeof parsed.takes !== "object") {
      return {};
    }
    const restored: TakesByBeat = {};
    for (const [beatId, value] of Object.entries(parsed.takes as Record<string, unknown>)) {
      if (!Array.isArray(value)) continue;
      const list: SessionTake[] = [];
      for (const candidate of value) {
        if (!candidate || typeof candidate !== "object") continue;
        const take = candidate as Partial<SessionTake>;
        if (
          typeof take.id !== "string"
          || typeof take.beatId !== "string"
          || take.beatId !== beatId
          || typeof take.filename !== "string"
          || typeof take.serverPath !== "string"
          || !take.serverPath
        ) {
          continue;
        }
        list.push({
          id: take.id,
          beatId,
          filename: take.filename,
          url: fileUrl(take.serverPath),
          size: typeof take.size === "number" ? take.size : 0,
          createdAt: typeof take.createdAt === "number" ? take.createdAt : 0,
          uploadState: "uploaded",
          serverPath: take.serverPath,
          metadataPath: typeof take.metadataPath === "string" ? take.metadataPath : undefined,
          recordingMetadata: take.recordingMetadata,
          processState:
            take.processState === "done" || take.processState === "error"
              ? take.processState
              : "idle",
          processMessage:
            take.processState === "running"
              ? "Processing interrupted · resume status"
              : typeof take.processMessage === "string"
                ? take.processMessage
                : undefined,
          processJobId: typeof take.processJobId === "string" ? take.processJobId : undefined,
          qualityStatus: take.qualityStatus,
          qualityMessage: typeof take.qualityMessage === "string" ? take.qualityMessage : undefined,
          verdictPath: typeof take.verdictPath === "string" ? take.verdictPath : undefined,
        });
      }
      if (list.length) restored[beatId] = list;
    }
    return restored;
  } catch {
    return {};
  }
}
