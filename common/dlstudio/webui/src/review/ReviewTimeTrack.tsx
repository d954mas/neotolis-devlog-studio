import type { JSX } from "preact";
import { useRef, useState } from "preact/hooks";

import type {
  BlobRef,
  FrameClock,
  FrameSelection,
} from "./types";
import {
  clampFrame,
  formatSelection,
  frameCount,
} from "./types";
import { useReviewWaveform } from "./useReviewWaveform";
import { WaveformShape } from "./WaveformShape";

type TrackContext = FrameClock & {
  artifact: BlobRef;
};

type ReviewTimeTrackProps = {
  context: TrackContext;
  frame: number;
  selection: FrameSelection;
  mode: "select" | "seek";
  version: "current" | "previous";
  markers?: ReadonlyArray<{ id: string; frame: number }>;
  onSelect?: (
    selection: FrameSelection,
    focusFrame: number,
  ) => void;
  onSeek: (frame: number) => void;
};

type Point = {
  x: number;
  y: number;
};

function frameAtPointer(
  event: JSX.TargetedPointerEvent<HTMLDivElement>,
  totalFrames: number,
): number {
  const bounds = event.currentTarget.getBoundingClientRect();
  const ratio = Math.max(
    0,
    Math.min(0.999999, (event.clientX - bounds.left) / bounds.width),
  );
  return Math.floor(ratio * totalFrames);
}

export function ReviewTimeTrack({
  context,
  frame,
  selection,
  mode,
  version,
  markers = [],
  onSelect,
  onSeek,
}: ReviewTimeTrackProps) {
  const [dragSelection, setDragSelection] =
    useState<FrameSelection | null>(null);
  const dragAnchor = useRef<number | null>(null);
  const dragOrigin = useRef<Point | null>(null);
  const dragging = useRef(false);
  const keyboardAnchor = useRef<number | null>(null);
  const keyboardFocus = useRef<number | null>(null);
  const waveform = useReviewWaveform(
    context.artifact,
    context.duration_ns,
  );
  const totalFrames = frameCount(context);
  const visibleSelection = dragSelection ?? selection;
  const currentFrameSelection = {
    startFrame: frame,
    endFrameExclusive: frame + 1,
  };
  const readoutSelection =
    mode === "seek" ? currentFrameSelection : visibleSelection;
  const selectionDescriptionId =
    `${version}-review-track-selection-${context.artifact.sha256}`;
  const versionLabel = version === "previous" ? "До" : "Сейчас";

  function commitSingle(candidate: number) {
    const next = clampFrame(candidate, context);
    keyboardAnchor.current = null;
    keyboardFocus.current = null;
    if (mode === "select" && onSelect) {
      onSelect(
        { startFrame: next, endFrameExclusive: next + 1 },
        next,
      );
    } else {
      onSeek(next);
    }
  }

  function pointerSelection(
    event: JSX.TargetedPointerEvent<HTMLDivElement>,
  ): { selection: FrameSelection; focusFrame: number } {
    const pointedFrame = frameAtPointer(event, totalFrames);
    const anchor = dragAnchor.current ?? pointedFrame;
    return {
      selection: {
        startFrame: Math.min(anchor, pointedFrame),
        endFrameExclusive: Math.max(anchor, pointedFrame) + 1,
      },
      focusFrame: pointedFrame,
    };
  }

  function handlePointerDown(
    event: JSX.TargetedPointerEvent<HTMLDivElement>,
  ) {
    if (event.button !== 0 || !event.isPrimary) return;
    const pointedFrame = frameAtPointer(event, totalFrames);
    keyboardAnchor.current = null;
    keyboardFocus.current = null;
    dragAnchor.current = pointedFrame;
    dragOrigin.current = { x: event.clientX, y: event.clientY };
    dragging.current = false;
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function handlePointerMove(
    event: JSX.TargetedPointerEvent<HTMLDivElement>,
  ) {
    if (dragAnchor.current === null || dragOrigin.current === null) {
      return;
    }
    const deltaX = Math.abs(event.clientX - dragOrigin.current.x);
    const deltaY = Math.abs(event.clientY - dragOrigin.current.y);
    if (!dragging.current) {
      if (deltaY > 8 && deltaY > deltaX) {
        cancelPointerSelection();
        if (event.currentTarget.hasPointerCapture(event.pointerId)) {
          event.currentTarget.releasePointerCapture(event.pointerId);
        }
        return;
      }
      if (deltaX < 6 || deltaX < deltaY) return;
      dragging.current = true;
    }
    const next = pointerSelection(event);
    if (mode === "select") {
      setDragSelection(next.selection);
    } else {
      onSeek(next.focusFrame);
    }
  }

  function handlePointerUp(
    event: JSX.TargetedPointerEvent<HTMLDivElement>,
  ) {
    if (dragAnchor.current === null) return;
    const result = dragging.current
      ? pointerSelection(event)
      : {
          selection: {
            startFrame: dragAnchor.current,
            endFrameExclusive: dragAnchor.current + 1,
          },
          focusFrame: dragAnchor.current,
        };
    if (mode === "select" && onSelect) {
      if (dragging.current) {
        keyboardAnchor.current = dragAnchor.current;
        keyboardFocus.current = result.focusFrame;
      }
      onSelect(result.selection, result.focusFrame);
    } else {
      onSeek(result.focusFrame);
    }
    dragAnchor.current = null;
    dragOrigin.current = null;
    dragging.current = false;
    setDragSelection(null);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  }

  function cancelPointerSelection() {
    dragAnchor.current = null;
    dragOrigin.current = null;
    dragging.current = false;
    setDragSelection(null);
  }

  function handleKeyDown(
    event: JSX.TargetedKeyboardEvent<HTMLDivElement>,
  ) {
    if (event.key === "Home" || event.key === "End") {
      event.preventDefault();
      commitSingle(event.key === "Home" ? 0 : totalFrames - 1);
      return;
    }
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") {
      return;
    }
    event.preventDefault();
    const delta = event.key === "ArrowLeft" ? -1 : 1;
    if (mode === "seek" || !event.shiftKey || !onSelect) {
      commitSingle(frame + delta);
      return;
    }
    if (
      keyboardAnchor.current === null ||
      keyboardFocus.current === null
    ) {
      keyboardAnchor.current = frame;
      keyboardFocus.current = frame;
    }
    keyboardFocus.current = Math.max(
      0,
      Math.min(totalFrames - 1, keyboardFocus.current + delta),
    );
    const next = {
      startFrame: Math.min(
        keyboardAnchor.current,
        keyboardFocus.current,
      ),
      endFrameExclusive:
        Math.max(keyboardAnchor.current, keyboardFocus.current) + 1,
    };
    onSelect(next, keyboardFocus.current);
  }

  const waveformData = waveform.data;
  const showWaveform =
    waveformData !== null &&
    (waveform.status === "ready" || waveform.status === "no_audio");

  return (
    <div class="review-time-track-block">
      <div class={`review-time-track ${version}`}>
        <div
          class="time-range-track"
          role="slider"
          tabIndex={0}
          aria-label={`${versionLabel} · ${
            mode === "select"
              ? "кадр или диапазон для комментария"
              : "навигация по прошлой версии"
          }`}
          aria-valuemin={0}
          aria-valuemax={totalFrames - 1}
          aria-valuenow={frame}
          aria-valuetext={`${versionLabel} · ${formatSelection(
            readoutSelection,
            context,
          )}`}
          aria-describedby={
            mode === "seek" ? selectionDescriptionId : undefined
          }
          onKeyDown={handleKeyDown}
          onBlur={() => {
            keyboardAnchor.current = null;
            keyboardFocus.current = null;
          }}
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          onPointerCancel={cancelPointerSelection}
          onLostPointerCapture={cancelPointerSelection}
        >
          {waveform.status === "loading" && (
            <span
              class="time-range-waveform-loading"
              aria-hidden="true"
            />
          )}
          {showWaveform && (
            <WaveformShape
              className="waveform-shape"
              peaksMilli={waveformData.peaksMilli}
              noAudio={waveform.status === "no_audio"}
            />
          )}
          {markers.map((marker) => (
            <span
              key={marker.id}
              class="time-range-marker"
              style={{
                left: `${
                  ((clampFrame(marker.frame, context) + 0.5) /
                    totalFrames) *
                  100
                }%`,
              }}
              aria-hidden="true"
            />
          ))}
          <span
            class="time-range-selection"
            style={{
              left: `${
                (visibleSelection.startFrame / totalFrames) * 100
              }%`,
              width: `${
                ((visibleSelection.endFrameExclusive -
                  visibleSelection.startFrame) /
                  totalFrames) *
                100
              }%`,
            }}
            aria-hidden="true"
          />
          <span
            class="time-range-playhead"
            style={{
              left: `${((frame + 0.5) / totalFrames) * 100}%`,
            }}
            aria-hidden="true"
          />
        </div>
        {mode === "seek" && (
          <span id={selectionDescriptionId} class="sr-only">
            Исходное замечание: {formatSelection(selection, context)}
          </span>
        )}
        {waveform.status === "error" && (
          <div class="time-range-waveform-status" role="status">
            <span>Форма звука недоступна</span>
            <button
              type="button"
              class="quiet"
              aria-label="Повторить форму звука"
              onClick={waveform.retry}
            >
              Повторить
            </button>
          </div>
        )}
        {waveform.status === "no_audio" && (
          <span class="time-range-no-audio" role="status">
            В этой версии нет звука
          </span>
        )}
      </div>
      <strong class="time-range-readout">
        {formatSelection(readoutSelection, context)}
      </strong>
    </div>
  );
}
