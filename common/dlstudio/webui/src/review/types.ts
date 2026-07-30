import type { components } from "../api/v3.gen";

export type ReviewContext = components["schemas"]["ReviewContext"];
export type ReviewFindingBody = components["schemas"]["ReviewFindingBody"];
export type ReviewRegion = components["schemas"]["ReviewRegionBody"];
export type ReviewTimelineItem = components["schemas"]["ReviewTimelineItem"];
export type WorkflowStatus = components["schemas"]["WorkflowStatus"];

export type FrameSelection = {
  startFrame: number;
  endFrameExclusive: number;
};

export function framesPerSecond(context: ReviewContext): number {
  return context.fps_num / context.fps_den;
}

export function frameCount(context: ReviewContext): number {
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
  context: ReviewContext,
): number {
  return (frame * context.fps_den) / context.fps_num;
}

export function nsToFrame(
  timeNs: number,
  context: ReviewContext,
): number {
  return Math.floor(
    (timeNs * context.fps_num) /
      (1_000_000_000 * context.fps_den),
  );
}

export function nsToFrameCeil(
  timeNs: number,
  context: ReviewContext,
): number {
  return Math.ceil(
    (timeNs * context.fps_num) /
      (1_000_000_000 * context.fps_den),
  );
}

export function clampFrame(frame: number, context: ReviewContext): number {
  return Math.max(0, Math.min(frameCount(context) - 1, frame));
}

export function formatTimecode(
  frame: number,
  context: ReviewContext,
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
  context: ReviewContext,
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

export function artifactVideoUrl(context: ReviewContext): string {
  return `/api/v3/review/artifacts/${context.artifact.sha256}?size=${context.artifact.size}`;
}
