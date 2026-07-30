import type { components } from "../api/v3.gen";

export type ReviewContext = components["schemas"]["ReviewContext"];
export type ReviewFindingBody = components["schemas"]["ReviewFindingBody"];
export type ReviewVerdict = components["schemas"]["ReviewVerdict"];
export type ReviewRegion = components["schemas"]["ReviewRegionBody"];
export type ReviewTimelineItem = components["schemas"]["ReviewTimelineItem"];
export type ReviewTaskPack = components["schemas"]["ReviewTaskPack"];
export type WorkflowStatus = components["schemas"]["WorkflowStatus"];
export type BlobRef = components["schemas"]["BlobRef"];

export type FrameClock = {
  duration_ns: number;
  fps_num: number;
  fps_den: number;
};

export type ResolutionStatus =
  | "unresolved"
  | "fixed"
  | "obsolete"
  | "still_wrong";

export type ResolutionDraft = {
  status: ResolutionStatus;
  currentFindingId: string | null;
};

export type FrameSelection = {
  startFrame: number;
  endFrameExclusive: number;
};

export function framesPerSecond(context: FrameClock): number {
  return context.fps_num / context.fps_den;
}

export function frameCount(context: FrameClock): number {
  return Math.max(
    1,
    Math.ceil(
      (context.duration_ns * context.fps_num) /
        (1_000_000_000 * context.fps_den),
    ),
  );
}

export function frameToSeconds(
  frame: number,
  context: FrameClock,
): number {
  return (frame * context.fps_den) / context.fps_num;
}

export function nsToFrame(
  timeNs: number,
  context: FrameClock,
): number {
  return Math.floor(
    (timeNs * context.fps_num) /
      (1_000_000_000 * context.fps_den),
  );
}

export function nsToFrameCeil(
  timeNs: number,
  context: FrameClock,
): number {
  return Math.ceil(
    (timeNs * context.fps_num) /
      (1_000_000_000 * context.fps_den),
  );
}

export function clampFrame(frame: number, context: FrameClock): number {
  return Math.max(0, Math.min(frameCount(context) - 1, frame));
}

export function formatTimecode(
  frame: number,
  context: FrameClock,
): string {
  const nominalFps = Math.max(1, Math.round(framesPerSecond(context)));
  const totalSeconds = Math.floor(frame / nominalFps);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  const frameInSecond = frame % nominalFps;
  const timecode = [hours, minutes, seconds, frameInSecond]
    .map((part) => String(part).padStart(2, "0"))
    .join(":");
  return context.fps_num % context.fps_den === 0
    ? timecode
    : `${timecode} NDF`;
}

export function formatSelection(
  selection: FrameSelection,
  context: FrameClock,
): string {
  if (selection.endFrameExclusive === selection.startFrame + 1) {
    return `Кадр ${selection.startFrame} · ${formatTimecode(
      selection.startFrame,
      context,
    )}`;
  }
  return `Кадры ${selection.startFrame}–${
    selection.endFrameExclusive - 1
  } · ${formatTimecode(selection.startFrame, context)}–${formatTimecode(
    selection.endFrameExclusive - 1,
    context,
  )}`;
}

export function mapFrameByPresentationTime(
  frame: number,
  from: FrameClock,
  to: FrameClock,
): number {
  return clampFrame(
    Math.round(
      (frame * from.fps_den * to.fps_num) /
        (from.fps_num * to.fps_den),
    ),
    to,
  );
}

export function mapFrameBoundaryByPresentationTime(
  frameBoundary: number,
  from: FrameClock,
  to: FrameClock,
): number {
  return Math.min(
    frameCount(to),
    Math.max(
      0,
      Math.round(
        (frameBoundary * from.fps_den * to.fps_num) /
          (from.fps_num * to.fps_den),
      ),
    ),
  );
}

export function sameBlobRef(
  first: BlobRef | null | undefined,
  second: BlobRef | null | undefined,
): boolean {
  return (
    first !== null &&
    first !== undefined &&
    second !== null &&
    second !== undefined &&
    first.sha256 === second.sha256 &&
    first.size === second.size
  );
}

export function artifactVideoUrl(artifact: BlobRef): string {
  return `/api/v3/review/artifacts/${artifact.sha256}?size=${artifact.size}`;
}

export function targetLabel(
  targetId: string,
  items: ReviewTimelineItem[],
): string {
  const item = items.find((candidate) => candidate.item_id === targetId);
  if (!item) return targetId;
  if (item.kind === "audio") {
    const role = item.lane.slice("audio.".length);
    const labels: Record<string, string> = {
      voice: "Голос",
      music: "Музыка",
      sfx: "Звуковой эффект",
      ambient: "Атмосфера",
    };
    return labels[role] ?? "Звук";
  }
  if (item.kind === "transition") {
    const labels: Record<string, string> = {
      fade: "Плавный переход",
      "fade in": "Появление",
      "fade out": "Затемнение",
      "dip black": "Переход через чёрный",
      "slide left": "Сдвиг влево",
      "slide right": "Сдвиг вправо",
    };
    return labels[item.label] ?? "Переход";
  }
  if (item.label.startsWith("solid ")) {
    return item.z === 0 ? "Фон" : "Графический слой";
  }
  return item.label;
}
