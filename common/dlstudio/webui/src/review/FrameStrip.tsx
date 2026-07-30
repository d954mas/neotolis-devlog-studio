import { useMemo, useRef, useState } from "preact/hooks";

import { ReviewTimeTrack } from "./ReviewTimeTrack";
import type {
  FrameSelection,
  ReviewContext,
} from "./types";
import {
  clampFrame,
  formatTimecode,
  frameCount,
  reviewFrameEvidenceUrl,
} from "./types";

type FrameStripProps = {
  context: ReviewContext;
  currentFrame: number;
  selection: FrameSelection;
  markers?: ReadonlyArray<{ id: string; frame: number }>;
  onSelect: (
    selection: FrameSelection,
    focusFrame: number,
  ) => void;
};

type FrameLoadState = {
  key: string;
  frames: ReadonlySet<number>;
};

const EMPTY_FRAMES: ReadonlySet<number> = new Set();

export function FrameStrip({
  context,
  currentFrame,
  selection,
  markers = [],
  onSelect,
}: FrameStripProps) {
  const [captureRequest, setCaptureRequest] = useState(0);
  const frameRequestKey =
    `${context.artifact.sha256}:${context.artifact.size}:${captureRequest}`;
  const currentRequestKey = useRef(frameRequestKey);
  currentRequestKey.current = frameRequestKey;
  const [loadedState, setLoadedState] = useState<FrameLoadState>(
    () => ({ key: frameRequestKey, frames: new Set() }),
  );
  const [failedState, setFailedState] = useState<FrameLoadState>(
    () => ({ key: frameRequestKey, frames: new Set() }),
  );
  const loadedFrames =
    loadedState.key === frameRequestKey
      ? loadedState.frames
      : EMPTY_FRAMES;
  const failedFrames =
    failedState.key === frameRequestKey
      ? failedState.frames
      : EMPTY_FRAMES;
  const totalFrames = frameCount(context);
  const thumbnails = useMemo(() => {
    const count = Math.min(9, totalFrames);
    return Array.from({ length: count }, (_, index) => {
      const frame =
        count === 1
          ? 0
          : Math.round((index * (totalFrames - 1)) / (count - 1));
      return {
        frame,
        imageUrl: reviewFrameEvidenceUrl(
          context.artifact,
          frame,
          160,
        ),
      };
    });
  }, [
    context.artifact.sha256,
    context.artifact.size,
    totalFrames,
  ]);

  function selectFrame(frame: number) {
    const next = clampFrame(frame, context);
    onSelect(
      { startFrame: next, endFrameExclusive: next + 1 },
      next,
    );
  }

  const allFailed =
    thumbnails.length > 0 && failedFrames.size === thumbnails.length;
  const hasFailures = failedFrames.size > 0;

  return (
    <section class="frame-navigator" aria-labelledby="frame-strip-title">
      <div class="frame-strip-head">
        <strong id="frame-strip-title">Где проблема?</strong>
        <span>Клик — кадр · протяните — диапазон</span>
      </div>

      {hasFailures && (
        <div class="filmstrip-fallback" role="status">
          <span>
            {allFailed
              ? "Превью недоступны — выбрать время всё ещё можно на шкале."
              : "Некоторые превью недоступны; остальные можно использовать."}
          </span>
          <button
            type="button"
            class="quiet"
            aria-label="Повторить загрузку превью"
            onClick={() => setCaptureRequest((current) => current + 1)}
          >
            Повторить
          </button>
        </div>
      )}
      <div
        class="filmstrip"
        aria-label="Превью по всей длине ролика"
      >
        {thumbnails.map((thumbnail, index) => {
          const selected =
            thumbnail.frame >= selection.startFrame &&
            thumbnail.frame < selection.endFrameExclusive;
          const loaded = loadedFrames.has(thumbnail.frame);
          const failed = failedFrames.has(thumbnail.frame);
          return (
            <button
              type="button"
              class={`${selected ? "selected" : ""} ${
                currentFrame === thumbnail.frame ? "active" : ""
              } ${loaded ? "loaded" : "loading"} ${
                failed ? "failed" : ""
              }`}
              key={`${thumbnail.frame}:${captureRequest}`}
              onClick={() => selectFrame(thumbnail.frame)}
              aria-pressed={selected}
              aria-label={`Выбрать кадр ${
                thumbnail.frame
              }, ${formatTimecode(thumbnail.frame, context)}${
                failed ? ", превью недоступно" : ""
              }`}
            >
              <img
                src={thumbnail.imageUrl}
                alt=""
                loading={index < 4 ? "eager" : "lazy"}
                onLoad={() => {
                  setLoadedState((current) => {
                    if (currentRequestKey.current !== frameRequestKey) {
                      return current;
                    }
                    const next = new Set(
                      current.key === frameRequestKey
                        ? current.frames
                        : EMPTY_FRAMES,
                    );
                    next.add(thumbnail.frame);
                    return { key: frameRequestKey, frames: next };
                  });
                }}
                onError={() => {
                  setFailedState((current) => {
                    if (currentRequestKey.current !== frameRequestKey) {
                      return current;
                    }
                    const next = new Set(
                      current.key === frameRequestKey
                        ? current.frames
                        : EMPTY_FRAMES,
                    );
                    next.add(thumbnail.frame);
                    return { key: frameRequestKey, frames: next };
                  });
                }}
              />
              <span>{formatTimecode(thumbnail.frame, context)}</span>
            </button>
          );
        })}
      </div>

      <ReviewTimeTrack
        context={context}
        frame={currentFrame}
        selection={selection}
        mode="select"
        version="current"
        markers={markers}
        onSelect={onSelect}
        onSeek={selectFrame}
      />
    </section>
  );
}
