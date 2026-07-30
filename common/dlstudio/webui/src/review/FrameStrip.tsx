import type { JSX } from "preact";
import { useEffect, useRef, useState } from "preact/hooks";
import type { FrameSelection, ReviewContext } from "./types";
import {
  artifactVideoUrl,
  clampFrame,
  formatSelection,
  formatTimecode,
  frameCount,
  frameToSeconds,
} from "./types";

type Thumbnail = {
  frame: number;
  imageUrl: string;
};

type Point = {
  x: number;
  y: number;
};

type FrameStripProps = {
  context: ReviewContext;
  currentFrame: number;
  selection: FrameSelection;
  onSelect: (selection: FrameSelection, focusFrame: number) => void;
};

function once(media: HTMLVideoElement, eventName: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const cleanup = () => {
      media.removeEventListener(eventName, handleEvent);
      media.removeEventListener("error", handleError);
    };
    const handleEvent = () => {
      cleanup();
      resolve();
    };
    const handleError = () => {
      cleanup();
      reject(new Error("Не удалось получить превью кадров."));
    };
    media.addEventListener(eventName, handleEvent, { once: true });
    media.addEventListener("error", handleError, { once: true });
  });
}

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

export function FrameStrip({
  context,
  currentFrame,
  selection,
  onSelect,
}: FrameStripProps) {
  const [thumbnails, setThumbnails] = useState<Thumbnail[]>([]);
  const [failed, setFailed] = useState(false);
  const [captureRequest, setCaptureRequest] = useState(0);
  const [dragSelection, setDragSelection] =
    useState<FrameSelection | null>(null);
  const dragAnchor = useRef<number | null>(null);
  const dragOrigin = useRef<Point | null>(null);
  const dragging = useRef(false);
  const keyboardAnchor = useRef<number | null>(null);
  const keyboardFocus = useRef<number | null>(null);
  const totalFrames = frameCount(context);
  const visibleSelection = dragSelection ?? selection;

  useEffect(() => {
    let cancelled = false;
    setFailed(false);
    setThumbnails([]);
    const media = document.createElement("video");
    media.preload = "auto";
    media.muted = true;
    media.playsInline = true;
    media.src = artifactVideoUrl(context.artifact);

    async function capture() {
      if (media.readyState < HTMLMediaElement.HAVE_METADATA) {
        await once(media, "loadedmetadata");
      }
      const count = Math.min(9, totalFrames);
      const frames = Array.from({ length: count }, (_, index) =>
        count === 1
          ? 0
          : Math.round((index * (totalFrames - 1)) / (count - 1)),
      );
      const canvas = document.createElement("canvas");
      canvas.width = 120;
      canvas.height = Math.max(
        68,
        Math.round((120 * context.height) / context.width),
      );
      const painter = canvas.getContext("2d");
      if (!painter) throw new Error("Canvas is unavailable.");

      const next: Thumbnail[] = [];
      for (const frame of frames) {
        const time = Math.min(
          frameToSeconds(frame, context),
          Math.max(0, media.duration - 0.001),
        );
        if (
          media.readyState < HTMLMediaElement.HAVE_CURRENT_DATA ||
          Math.abs(media.currentTime - time) > 0.0005
        ) {
          media.currentTime = time;
          await once(media, "seeked");
        }
        if (cancelled) return;
        painter.drawImage(media, 0, 0, canvas.width, canvas.height);
        next.push({
          frame,
          imageUrl: canvas.toDataURL("image/jpeg", 0.68),
        });
      }
      if (!cancelled) setThumbnails(next);
    }

    void capture().catch(() => {
      if (!cancelled) setFailed(true);
    });
    return () => {
      cancelled = true;
      media.removeAttribute("src");
      media.load();
    };
  }, [
    context.artifact.sha256,
    context.artifact.size,
    context.fps_den,
    context.fps_num,
    context.height,
    context.width,
    captureRequest,
    totalFrames,
  ]);

  function selectFrame(frame: number) {
    const next = clampFrame(frame, context);
    keyboardAnchor.current = null;
    keyboardFocus.current = null;
    onSelect(
      { startFrame: next, endFrameExclusive: next + 1 },
      next,
    );
  }

  function pointerSelection(
    event: JSX.TargetedPointerEvent<HTMLDivElement>,
  ): { selection: FrameSelection; focusFrame: number } {
    const frame = frameAtPointer(event, totalFrames);
    const anchor = dragAnchor.current ?? frame;
    return {
      selection: {
        startFrame: Math.min(anchor, frame),
        endFrameExclusive: Math.max(anchor, frame) + 1,
      },
      focusFrame: frame,
    };
  }

  function handlePointerDown(
    event: JSX.TargetedPointerEvent<HTMLDivElement>,
  ) {
    const frame = frameAtPointer(event, totalFrames);
    keyboardAnchor.current = null;
    keyboardFocus.current = null;
    dragAnchor.current = frame;
    dragOrigin.current = { x: event.clientX, y: event.clientY };
    dragging.current = false;
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function handlePointerMove(
    event: JSX.TargetedPointerEvent<HTMLDivElement>,
  ) {
    if (dragAnchor.current === null || dragOrigin.current === null) return;
    const deltaX = Math.abs(event.clientX - dragOrigin.current.x);
    const deltaY = Math.abs(event.clientY - dragOrigin.current.y);
    if (!dragging.current) {
      if (deltaX < 6 || deltaX < deltaY) return;
      dragging.current = true;
    }
    setDragSelection(pointerSelection(event).selection);
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
    if (dragging.current) {
      keyboardAnchor.current = dragAnchor.current;
      keyboardFocus.current = result.focusFrame;
    } else {
      keyboardAnchor.current = null;
      keyboardFocus.current = null;
    }
    onSelect(result.selection, result.focusFrame);
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
      selectFrame(event.key === "Home" ? 0 : totalFrames - 1);
      return;
    }
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const delta = event.key === "ArrowLeft" ? -1 : 1;
    if (!event.shiftKey) {
      selectFrame(currentFrame + delta);
      return;
    }
    if (keyboardAnchor.current === null || keyboardFocus.current === null) {
      keyboardAnchor.current = currentFrame;
      keyboardFocus.current = currentFrame;
    }
    keyboardFocus.current = Math.max(
      0,
      Math.min(totalFrames - 1, keyboardFocus.current + delta),
    );
    const next = {
      startFrame: Math.min(keyboardAnchor.current, keyboardFocus.current),
      endFrameExclusive:
        Math.max(keyboardAnchor.current, keyboardFocus.current) + 1,
    };
    onSelect(next, keyboardFocus.current);
  }

  return (
    <section class="frame-navigator" aria-labelledby="frame-strip-title">
      <div class="frame-strip-head">
        <strong id="frame-strip-title">Где проблема?</strong>
        <span>Клик — кадр · протяните — диапазон</span>
      </div>

      {failed ? (
        <div class="filmstrip-fallback" role="status">
          <span>
            Превью недоступны — выбрать время всё ещё можно на шкале.
          </span>
          <button
            type="button"
            class="quiet"
            onClick={() => setCaptureRequest((current) => current + 1)}
          >
            Повторить
          </button>
        </div>
      ) : thumbnails.length === 0 ? (
        <div
          class="filmstrip filmstrip-loading"
          aria-label="Готовим превью кадров"
        >
          {Array.from({ length: 7 }, (_, index) => (
            <span key={index} />
          ))}
        </div>
      ) : (
        <div
          class="filmstrip"
          aria-label="Превью по всей длине ролика"
        >
          {thumbnails.map((thumbnail) => {
            const selected =
              thumbnail.frame >= visibleSelection.startFrame &&
              thumbnail.frame < visibleSelection.endFrameExclusive;
            return (
              <button
                type="button"
                class={`${selected ? "selected" : ""} ${
                  currentFrame === thumbnail.frame ? "active" : ""
                }`}
                key={thumbnail.frame}
                onClick={() => selectFrame(thumbnail.frame)}
                aria-pressed={selected}
                aria-label={`Выбрать кадр ${thumbnail.frame}, ${formatTimecode(
                  thumbnail.frame,
                  context,
                )}`}
              >
                <img src={thumbnail.imageUrl} alt="" />
                <span>{formatTimecode(thumbnail.frame, context)}</span>
              </button>
            );
          })}
        </div>
      )}

      <div
        class="time-range-track"
        role="slider"
        tabIndex={0}
        aria-label="Кадр или диапазон для комментария"
        aria-valuemin={0}
        aria-valuemax={totalFrames - 1}
        aria-valuenow={currentFrame}
        aria-valuetext={formatSelection(visibleSelection, context)}
        onKeyDown={handleKeyDown}
        onBlur={() => {
          keyboardAnchor.current = null;
          keyboardFocus.current = null;
        }}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerCancel={cancelPointerSelection}
      >
        <span
          class="time-range-selection"
          style={{
            left: `${(visibleSelection.startFrame / totalFrames) * 100}%`,
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
            left: `${((currentFrame + 0.5) / totalFrames) * 100}%`,
          }}
          aria-hidden="true"
        />
      </div>
      <strong class="time-range-readout">
        {formatSelection(visibleSelection, context)}
      </strong>
    </section>
  );
}
