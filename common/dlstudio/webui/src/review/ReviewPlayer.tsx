import type { JSX, RefObject } from "preact";
import { useEffect, useRef, useState } from "preact/hooks";
import type {
  ReviewContext,
  ReviewRegion,
  ReviewTaskPack,
} from "./types";
import {
  artifactVideoUrl,
  clampFrame,
  frameToSeconds,
  formatTimecode,
  framesPerSecond,
} from "./types";

type ReviewPlayerProps = {
  context: ReviewContext;
  currentFrame: number;
  videoRef: RefObject<HTMLVideoElement>;
  region: ReviewRegion | null;
  comparison: {
    context: ReviewTaskPack;
    frame: number;
    region: ReviewRegion | null;
    sameMedia: boolean;
  } | null;
  comparisonLabel: string | null;
  onCurrentMediaState: (state: ReviewMediaState) => void;
  onComparisonMediaState: (state: ReviewMediaState) => void;
  onFrame: (frame: number) => void;
  onRegion: (region: ReviewRegion | null) => void;
  onSeek: (frame: number) => void;
};

export type ReviewMediaState = "loading" | "ready" | "error";

type Point = { x: number; y: number };

function normalizedPoint(
  event: JSX.TargetedPointerEvent<SVGSVGElement>,
): Point {
  const bounds = event.currentTarget.getBoundingClientRect();
  return {
    x: Math.round(
      Math.max(0, Math.min(1, (event.clientX - bounds.left) / bounds.width)) *
        1000,
    ),
    y: Math.round(
      Math.max(0, Math.min(1, (event.clientY - bounds.top) / bounds.height)) *
        1000,
    ),
  };
}

function regionBetween(first: Point, second: Point): ReviewRegion {
  return {
    x_milli: Math.min(first.x, second.x),
    y_milli: Math.min(first.y, second.y),
    width_milli: Math.abs(first.x - second.x),
    height_milli: Math.abs(first.y - second.y),
  };
}

export function ReviewPlayer({
  context,
  currentFrame,
  videoRef,
  region,
  comparison,
  comparisonLabel,
  onCurrentMediaState,
  onComparisonMediaState,
  onFrame,
  onRegion,
  onSeek,
}: ReviewPlayerProps) {
  const playerRef = useRef<HTMLElement>(null);
  const comparisonVideoRef = useRef<HTMLVideoElement>(null);
  const currentTimeBeforeComparison = useRef<number | null>(null);
  const wasPlayingBeforeComparison = useRef(false);
  const dragStart = useRef<Point | null>(null);
  const regionBeforeDrag = useRef<ReviewRegion | null>(null);
  const wasPlayingBeforeDrag = useRef(false);
  const [draggingRegion, setDraggingRegion] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [muted, setMuted] = useState(false);
  const [volume, setVolume] = useState(1);
  const [fullscreen, setFullscreen] = useState(false);
  const [comparisonFrame, setComparisonFrame] = useState<number | null>(
    null,
  );
  const readOnly = comparison !== null;
  const displayContext = comparison?.context ?? context;
  const displayFrame =
    comparison === null
      ? currentFrame
      : (comparisonFrame ?? comparison.frame);
  const displayRegion = comparison?.region ?? region;

  useEffect(() => {
    const video = videoRef.current;
    onCurrentMediaState(
      video !== null &&
        video.readyState >= HTMLMediaElement.HAVE_METADATA
        ? "ready"
        : "loading",
    );
  }, [
    context.artifact.sha256,
    context.artifact.size,
    onCurrentMediaState,
    videoRef,
  ]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    const syncFrame = () => {
      const next = clampFrame(
        Math.floor(video.currentTime * framesPerSecond(context) + 0.0001),
        context,
      );
      if (!readOnly) {
        onFrame(next);
        setPlaying(!video.paused);
      }
    };
    const syncVolume = () => {
      if (!readOnly) {
        setMuted(video.muted);
        setVolume(video.volume);
      }
    };
    video.addEventListener("timeupdate", syncFrame);
    video.addEventListener("seeked", syncFrame);
    video.addEventListener("play", syncFrame);
    video.addEventListener("pause", syncFrame);
    video.addEventListener("volumechange", syncVolume);
    return () => {
      video.removeEventListener("timeupdate", syncFrame);
      video.removeEventListener("seeked", syncFrame);
      video.removeEventListener("play", syncFrame);
      video.removeEventListener("pause", syncFrame);
      video.removeEventListener("volumechange", syncVolume);
    };
  }, [
    context.duration_ns,
    context.fps_den,
    context.fps_num,
    onFrame,
    readOnly,
    videoRef,
  ]);

  useEffect(() => {
    const syncFullscreen = () => {
      setFullscreen(document.fullscreenElement === playerRef.current);
    };
    document.addEventListener("fullscreenchange", syncFullscreen);
    return () => {
      document.removeEventListener("fullscreenchange", syncFullscreen);
    };
  }, []);

  useEffect(() => {
    const currentVideo = videoRef.current;
    if (!comparison || !currentVideo) {
      setComparisonFrame(null);
      return;
    }
    wasPlayingBeforeComparison.current = !currentVideo.paused;
    currentVideo.pause();
    setComparisonFrame(comparison.frame);
    const activeVideo = comparison.sameMedia
      ? currentVideo
      : comparisonVideoRef.current;
    if (!activeVideo) return;

    if (comparison.sameMedia) {
      currentTimeBeforeComparison.current = currentVideo.currentTime;
    } else {
      activeVideo.volume = currentVideo.volume;
      activeVideo.muted = currentVideo.muted;
      onComparisonMediaState(
        activeVideo.readyState >= HTMLMediaElement.HAVE_METADATA
          ? "ready"
          : "loading",
      );
    }
    const seekComparisonFrame = () => {
      activeVideo.currentTime = frameToSeconds(
        comparison.frame,
        comparison.context,
      );
    };
    const syncComparison = () => {
      setComparisonFrame(
        clampFrame(
          Math.floor(
            activeVideo.currentTime *
              framesPerSecond(comparison.context) +
              0.0001,
          ),
          comparison.context,
        ),
      );
      setPlaying(!activeVideo.paused);
      setMuted(activeVideo.muted);
      setVolume(activeVideo.volume);
    };
    activeVideo.addEventListener("timeupdate", syncComparison);
    activeVideo.addEventListener("seeked", syncComparison);
    activeVideo.addEventListener("play", syncComparison);
    activeVideo.addEventListener("pause", syncComparison);
    activeVideo.addEventListener("volumechange", syncComparison);
    if (activeVideo.readyState >= HTMLMediaElement.HAVE_METADATA) {
      seekComparisonFrame();
      syncComparison();
    } else {
      activeVideo.addEventListener(
        "loadedmetadata",
        seekComparisonFrame,
        {
          once: true,
        },
      );
      activeVideo.addEventListener("loadedmetadata", syncComparison, {
        once: true,
      });
    }
    return () => {
      activeVideo.pause();
      activeVideo.removeEventListener(
        "loadedmetadata",
        seekComparisonFrame,
      );
      activeVideo.removeEventListener(
        "loadedmetadata",
        syncComparison,
      );
      activeVideo.removeEventListener("timeupdate", syncComparison);
      activeVideo.removeEventListener("seeked", syncComparison);
      activeVideo.removeEventListener("play", syncComparison);
      activeVideo.removeEventListener("pause", syncComparison);
      activeVideo.removeEventListener(
        "volumechange",
        syncComparison,
      );
      if (
        comparison.sameMedia &&
        currentTimeBeforeComparison.current !== null
      ) {
        currentVideo.currentTime =
          currentTimeBeforeComparison.current;
      } else if (!comparison.sameMedia) {
        currentVideo.volume = activeVideo.volume;
        currentVideo.muted = activeVideo.muted;
      }
      currentTimeBeforeComparison.current = null;
      setComparisonFrame(null);
      setPlaying(false);
      setMuted(currentVideo.muted);
      setVolume(currentVideo.volume);
      if (wasPlayingBeforeComparison.current) {
        void currentVideo.play().catch(() => setPlaying(false));
      }
      wasPlayingBeforeComparison.current = false;
    };
  }, [
    comparison?.context.artifact.sha256,
    comparison?.context.artifact.size,
    comparison?.context.fps_den,
    comparison?.context.fps_num,
    comparison?.frame,
    comparison?.sameMedia,
    onComparisonMediaState,
    videoRef,
  ]);

  function activeVideo(): HTMLVideoElement | null {
    if (comparison && !comparison.sameMedia) {
      return comparisonVideoRef.current;
    }
    return videoRef.current;
  }

  function step(delta: number) {
    if (comparison) {
      const next = clampFrame(displayFrame + delta, displayContext);
      const video = activeVideo();
      video?.pause();
      if (video) {
        video.currentTime = frameToSeconds(next, displayContext);
      }
      setComparisonFrame(next);
      setPlaying(false);
      return;
    }
    onSeek(clampFrame(currentFrame + delta, context));
  }

  function togglePlayback() {
    const video = activeVideo();
    if (!video) return;
    if (video.paused) {
      void video.play().catch(() => setPlaying(false));
    } else {
      video.pause();
    }
  }

  function toggleMute() {
    const video = activeVideo();
    if (!video) return;
    video.muted = !video.muted;
  }

  function changeVolume(event: JSX.TargetedInputEvent<HTMLInputElement>) {
    const video = activeVideo();
    if (!video) return;
    video.volume = Number(event.currentTarget.value);
    if (video.volume > 0) video.muted = false;
  }

  function toggleFullscreen() {
    const player = playerRef.current;
    if (!player) return;
    if (document.fullscreenElement) {
      void document.exitFullscreen();
    } else {
      void player.requestFullscreen();
    }
  }

  function handleKeyDown(
    event: JSX.TargetedKeyboardEvent<HTMLElement>,
  ) {
    if (event.target !== event.currentTarget) return;
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      event.preventDefault();
      step(event.key === "ArrowLeft" ? -1 : 1);
    }
    if (event.key === " ") {
      event.preventDefault();
      togglePlayback();
    }
  }

  function startRegion(
    event: JSX.TargetedPointerEvent<SVGSVGElement>,
  ) {
    if (readOnly) return;
    const video = videoRef.current;
    wasPlayingBeforeDrag.current = Boolean(video && !video.paused);
    video?.pause();
    event.currentTarget.setPointerCapture(event.pointerId);
    dragStart.current = normalizedPoint(event);
    regionBeforeDrag.current = region;
    setDraggingRegion(true);
  }

  function moveRegion(
    event: JSX.TargetedPointerEvent<SVGSVGElement>,
  ) {
    if (readOnly) return;
    if (!dragStart.current) return;
    const next = regionBetween(
      dragStart.current,
      normalizedPoint(event),
    );
    if (next.width_milli >= 4 || next.height_milli >= 4) {
      onRegion(next);
    }
  }

  function finishRegion(
    event: JSX.TargetedPointerEvent<SVGSVGElement>,
  ) {
    if (readOnly) return;
    if (!dragStart.current) return;
    const next = regionBetween(
      dragStart.current,
      normalizedPoint(event),
    );
    if (next.width_milli >= 8 && next.height_milli >= 8) {
      onRegion(next);
    } else {
      onRegion(regionBeforeDrag.current);
      if (!wasPlayingBeforeDrag.current) {
        void videoRef.current?.play().catch(() => setPlaying(false));
      }
    }
    dragStart.current = null;
    regionBeforeDrag.current = null;
    wasPlayingBeforeDrag.current = false;
    setDraggingRegion(false);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  }

  function cancelRegion() {
    onRegion(regionBeforeDrag.current);
    if (wasPlayingBeforeDrag.current) {
      void videoRef.current?.play().catch(() => setPlaying(false));
    }
    dragStart.current = null;
    regionBeforeDrag.current = null;
    wasPlayingBeforeDrag.current = false;
    setDraggingRegion(false);
  }

  return (
    <section
      ref={playerRef}
      class="review-player"
      aria-label="Точное видео для ревью"
      tabIndex={0}
      onKeyDown={handleKeyDown}
    >
      <div class="player-readout">
        <span class="live-dot" aria-hidden="true" />
        <strong>Кадр {displayFrame}</strong>
        <span>{formatTimecode(displayFrame, displayContext)}</span>
        <span class="player-inline-hint">
          {readOnly
            ? "До · разметка отключена"
            : "Клик — пауза · протяните — область"}
        </span>
      </div>
      <div class="video-well">
        <div
          class={`video-stage ${readOnly ? "showing-old" : ""}`}
          style={{
            aspectRatio: `${displayContext.width} / ${displayContext.height}`,
            maxWidth: `${
              (displayContext.width / displayContext.height) * 45
            }vh`,
          }}
        >
          <video
            key={`${context.artifact.sha256}:${context.artifact.size}`}
            ref={videoRef}
            class={
              comparison && !comparison.sameMedia
                ? "current-video hidden-by-comparison"
                : "current-video"
            }
            src={artifactVideoUrl(context.artifact)}
            preload="metadata"
            playsInline
            onLoadStart={() => onCurrentMediaState("loading")}
            onLoadedMetadata={() => onCurrentMediaState("ready")}
            onError={() => onCurrentMediaState("error")}
          />
          {comparison && !comparison.sameMedia && (
            <video
              ref={comparisonVideoRef}
              class="comparison-video"
              src={artifactVideoUrl(comparison.context.artifact)}
              preload="metadata"
              playsInline
              onLoadStart={() => onComparisonMediaState("loading")}
              onLoadedMetadata={() => onComparisonMediaState("ready")}
              onError={() => onComparisonMediaState("error")}
            />
          )}
          {comparisonLabel && (
            <div
              class={`comparison-ribbon ${readOnly ? "old" : "current"}`}
              role="status"
              aria-live="polite"
            >
              {comparisonLabel}
            </div>
          )}
          <svg
            class={`region-layer ${readOnly ? "read-only" : ""} ${
              draggingRegion ? "drawing" : ""
            }`}
            viewBox="0 0 1000 1000"
            preserveAspectRatio="none"
            aria-label={
              readOnly
                ? "Прошлая версия; область показана только для сравнения"
                : "Клик — воспроизведение, протягивание — область комментария"
            }
            aria-disabled={readOnly}
            onPointerDown={startRegion}
            onPointerMove={moveRegion}
            onPointerUp={finishRegion}
            onPointerCancel={cancelRegion}
          >
            {displayRegion && (
              <g>
                <rect
                  class="region-fill"
                  x={displayRegion.x_milli}
                  y={displayRegion.y_milli}
                  width={displayRegion.width_milli}
                  height={displayRegion.height_milli}
                />
                <rect
                  class="region-stroke"
                  x={displayRegion.x_milli}
                  y={displayRegion.y_milli}
                  width={displayRegion.width_milli}
                  height={displayRegion.height_milli}
                />
              </g>
            )}
          </svg>
        </div>
      </div>
      <div class="player-controls" aria-label="Управление видео">
        <button
          type="button"
          class="transport frame-step"
          onClick={() => step(-1)}
          aria-label="На один кадр назад"
        >
          ← 1
        </button>
        <button
          type="button"
          class="transport play"
          onClick={togglePlayback}
          aria-label={playing ? "Пауза" : "Смотреть"}
        >
          {playing ? "Пауза" : "Смотреть"}
        </button>
        <button
          type="button"
          class="transport frame-step"
          onClick={() => step(1)}
          aria-label="На один кадр вперёд"
        >
          1 →
        </button>
        <span class="control-spacer" />
        <button
          type="button"
          class="transport"
          onClick={toggleMute}
          aria-label={muted ? "Включить звук" : "Выключить звук"}
        >
          {muted ? "Без звука" : "Звук"}
        </button>
        <label class="volume-control">
          <span class="sr-only">Громкость</span>
          <input
            type="range"
            min="0"
            max="1"
            step="0.05"
            value={volume}
            onInput={changeVolume}
            aria-label="Громкость"
          />
        </label>
        <button
          type="button"
          class="transport fullscreen-control"
          onClick={toggleFullscreen}
          aria-label={
            fullscreen ? "Выйти из полного экрана" : "На весь экран"
          }
        >
          {fullscreen ? "Обычный вид" : "На весь экран"}
        </button>
        {!readOnly && !region && (
          <button
            type="button"
            class="transport preset-region"
            onClick={() => {
              videoRef.current?.pause();
              onRegion({
                x_milli: 200,
                y_milli: 200,
                width_milli: 600,
                height_milli: 600,
              });
            }}
            aria-label="Отметить центральную область кадра"
          >
            Центр кадра
          </button>
        )}
        {!readOnly && region && (
          <button
            type="button"
            class="transport clear-region"
            onClick={() => onRegion(null)}
          >
            Убрать область
          </button>
        )}
      </div>
      <p class="keyboard-hint">
        В фокусе плеера: ←/→ — по кадру · пробел — пауза
      </p>
    </section>
  );
}
