// Hand-written TypeScript types for the Studio v2 API contract.
// These mirror the frozen endpoints the api-agent implements. Timeline shapes
// track src/dlstudio/ir.py (pydantic). Anything the UI dumps generically
// (assets map, design internals) is typed loosely on purpose.

// ── GET /api/project ────────────────────────────────────────────────────────
export interface ProjectDesign {
  resolution: [number, number];
  fps: number;
}

export interface ProjectBeat {
  id: string;
  /** Optional on the model (Beat.title/vo/stage default to None). */
  title: string | null;
  vo: string | null;
  stage: string | null;
  face: FaceMode | string;
  /** null until the beat compiles (needs processed VO to measure). */
  duration: number | null;
  n_chunks: number;
  /** Processed VO wav path (null/"" until a take is processed). */
  audio: string | null;
  /** words.json path for this beat (null/"" until processed). */
  words: string | null;
  /** Whether a rendered MP4 currently exists for this beat. */
  rendered: boolean;
}

export interface ProductProduction {
  id: string;
  kind: "devlog" | "reel" | string;
  date: string;
  orientation: "landscape" | "vertical" | string;
  studio_ref: string;
  current: boolean;
}

export interface ProductOverview {
  id: string;
  title: string;
  current_production_id: string;
  productions: ProductProduction[];
}

export interface Project {
  edit_name: string;
  storage_identity: string;
  output: string;
  design: ProjectDesign;
  beats: ProjectBeat[];
  script_sha256: string;
  script_approved: boolean;
  product: ProductOverview | null;
}

export interface ScriptApprovalResult {
  script_sha256: string;
  script_approved: boolean;
  approved_by: string;
}

// ── GET /api/autopilot/checkpoint ──
export interface AutopilotWallTime {
  budget_minutes: number;
  elapsed_minutes: number;
  remaining_minutes: number;
  stage: string;
}

export interface AutopilotBlocker {
  severity: string;
  code: string;
  message: string;
  where?: string;
}

export interface AutopilotCheckpointRow {
  id: string;
  vo_thesis: string;
  shot: {
    src: string;
    provenance: string;
    source_role: string;
  };
  duration_seconds: number;
  quality_flags: string[];
  proposed_fix: string;
  approved: boolean;
}

export interface AutopilotCheckpointData {
  checkpoint_digest: string;
  wall_time: AutopilotWallTime;
  blockers: AutopilotBlocker[];
  notices?: AutopilotBlocker[];
  missing_inputs: string[];
  rows: AutopilotCheckpointRow[];
  approved_all: boolean;
  can_approve_all: boolean;
}

export type AutopilotRequestAction =
  | "replace_shot"
  | "request_capture"
  | "change_text";

export interface AutopilotApprovalResult {
  approved_count: number;
  changed_count: number;
  checkpoint: AutopilotCheckpointData;
}

export interface AutopilotChangeResult {
  status: "requested";
  request: {
    id: string;
    action: AutopilotRequestAction;
    shot_id: string;
    reason: string;
    requested_by: string;
    timestamp: string;
    status: "requested";
  };
}

export type FaceMode = "full" | "pip" | "none";

// ── GET /api/ir  →  Timeline (see src/dlstudio/ir.py) ───────────────────────
export interface WordSpan {
  t0: number;
  t1: number;
  text: string;
}

/** Transition is a small typed variant in the engine; kept open here. */
export interface Transition {
  kind?: string;
  dur?: number;
  [k: string]: unknown;
}

export interface IRAnim {
  prop: string;
  start: number;
  end: number;
  ease: string;
  t0: number;
  t1: number;
}

export interface IROverlayItem {
  chunk_index: number;
  z: number;
  t0: number;
  t1: number;
  anims: IRAnim[];
  transition_in: Transition | null;
  content_hash: string | null;
  asset_paths: string[];
}

export interface IRSegment {
  kind: "image" | "video";
  src: string;
  offset: number;
  t0: number;
  t1: number;
  ken_burns: boolean;
  loop: boolean;
  fit: "cover" | "contain";
  xfade: Transition | null;
}

export interface IRSfx {
  src: string;
  /** Beat-relative seconds (resolved from a word anchor). */
  t: number;
  gain_db: number;
}

export interface IRBeat {
  id: string;
  duration: number;
  audio: string;
  words_path: string;
  words: WordSpan[];
  segments: IRSegment[];
  overlays: IROverlayItem[];
  face: FaceMode;
  sfx: IRSfx[];
  transition_out: Transition | null;
}

export interface BeatPlacement {
  beat_id: string;
  t0: number;
}

export interface IRMusicSpan {
  src: string;
  t0: number;
  t1: number;
  offset: number;
  gain_db: number;
  fade_in: number;
  fade_out: number;
  duck: boolean;
}

export interface Duck {
  amount_db: number;
  threshold_db: number;
  attack_ms: number;
  release_ms: number;
}

export interface IRMix {
  music: IRMusicSpan[];
  duck: Duck;
  target_lufs: number;
  true_peak_db?: number;
}

export interface AssetProbe {
  path: string;
  kind: "image" | "video" | "audio" | "font" | "other";
  exists: boolean;
  duration: number | null;
  width: number | null;
  height: number | null;
  has_audio: boolean | null;
  readable: boolean | null;
}

export interface Timeline {
  edit_name: string;
  design: Record<string, unknown> & { resolution?: [number, number]; fps?: number };
  beats: IRBeat[];
  placements: BeatPlacement[];
  mix: IRMix;
  assets: Record<string, AssetProbe>;
  output: string;
  warnings: string[];
  diagnostics: CheckIssue[];
}

// ── GET /api/check ──────────────────────────────────────────────────────────
export type Severity = "error" | "warn";

export interface CheckIssue {
  severity: Severity;
  code: string;
  message: string;
  where: string;
}

export interface CheckReport {
  issues: CheckIssue[];
}

// ── GET/POST /api/feedback ──────────────────────────────────────────────────
export interface ReviewSuggestion {
  severity?: string; // crit | high | med | low
  category?: string; // mech | rerecord | redesign | ...
  effort?: string;
  what?: string;
  how?: string;
}

export interface ReviewSection {
  verdict?: string;
  main_fix?: string;
  suggestions?: ReviewSuggestion[];
  notes?: string;
  raw?: string;
  timestamp?: string;
  [k: string]: unknown;
}

/** Per-beat feedback: an object keyed by section ("vo" | "video"). */
export type BeatFeedback = Record<string, ReviewSection>;

/** Whole feedback document: beat_id -> BeatFeedback. */
export type Feedback = Record<string, BeatFeedback>;

// ── Actions & jobs ──────────────────────────────────────────────────────────
export interface TakeUploadResult {
  path: string;
  metadata_path?: string;
}

export interface ProcessTakeRequest {
  beat_id: string;
  recording_path: string;
  language?: string;
  model?: string;
}

export interface RenderBeatRequest {
  beat_id: string;
  /** Named profile ("540p", "1080p", "4k", …) or a literal pixel width.
   * Prefer the named profiles: the server resolves them orientation-aware
   * through ONE table shared with the CLI (defect 0.6), so the webui must
   * never compute pixel sizes itself. */
  width?: number | string;
  quality?: string;
}

export interface JobHandle {
  job_id: string;
}

export type JobState = "running" | "done" | "error";

export interface JobStatus {
  status: JobState;
  result?: unknown;
  error?: string;
}
