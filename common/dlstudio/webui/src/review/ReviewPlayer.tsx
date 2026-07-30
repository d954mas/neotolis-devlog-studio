import type { JSX, RefObject } from "preact";
import { useEffect, useRef, useState } from "preact/hooks";
import type { ReviewContext, ReviewRegion } from "./types";
import {
  artifactVideoUrl,
  clampFrame,
  formatTimecode,
  framesPerSecond,
} from "./types";

type ReviewPlayerProps = {
  context: ReviewContext;
  currentFrame: number;
  videoRef: RefObject<HTMLVideoElement>;
  region: ReviewRegion | null;
  onFrame: (frame: number) => void;
  onRegion: (region: ReviewRegion | null) => void;
  onSeek: (frame: number) => void;
};

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
  onFrame,
  onRegion,
  onSeek,
}: ReviewPlayerProps) {
  const playerRef = useRef<HTMLElement>(null);
  const dragStart = useRef<Point | null>(null);
  const regionBeforeDrag = useRef<ReviewRegion | null>(null);
  const wasPlayingBeforeDrag = useRef(false);
  const [draggingRegion, setDraggingRegion] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [muted, setMuted] = useState(false);
  const [volume, setVolume] = useState(1);
  const [fullscreen, setFullscreen] = useState(false);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    const syncFrame = () => {
      const next = clampFrame(
        Math.floor(video.currentTime * framesPerSecond(context) + 0.0001),
        context,
      );
      onFrame(next);
      setPlaying(!video.paused);
    };
    const syncVolume = () => {
      setMuted(video.muted);
      setVolume(video.volume);
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

  function step(delta: number) {
    onSeek(clampFrame(currentFrame + delta, context));
  }

  function togglePlayback() {
    const video = videoRef.current;
    if (!video) return;
    if (video.paused) {
      void video.play().catch(() => setPlaying(false));
    } else {
      video.pause();
    }
  }

  function toggleMute() {
    const video = videoRef.current;
    if (!video) return;
    video.muted = !video.muted;
  }

  function changeVolume(event: JSX.TargetedInputEvent<HTMLInputElement>) {
    const video = videoRef.current;
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
        <strong>Кадр {currentFrame}</strong>
        <span>{formatTimecode(currentFrame, context)}</span>
        <span class="player-inline-hint">
          Клик — пауза · протяните — область
        </span>
      </div>
      <div class="video-well">
        <div
          class="video-stage"
          style={{
            aspectRatio: `${context.width} / ${context.height}`,
            maxWidth: `${(context.width / context.height) * 45}vh`,
          }}
        >
          <video
            ref={videoRef}
            src={artifactVideoUrl(context)}
            preload="metadata"
            playsInline
          />
          <svg
            class={`region-layer ${
              draggingRegion ? "drawing" : ""
            }`}
            viewBox="0 0 1000 1000"
            preserveAspectRatio="none"
            aria-label="Клик — воспроизведение, протягивание — область комментария"
            onPointerDown={startRegion}
            onPointerMove={moveRegion}
            onPointerUp={finishRegion}
            onPointerCancel={cancelRegion}
          >
            {region && (
              <g>
                <rect
                  class="region-fill"
                  x={region.x_milli}
                  y={region.y_milli}
                  width={region.width_milli}
                  height={region.height_milli}
                />
                <rect
                  class="region-stroke"
                  x={region.x_milli}
                  y={region.y_milli}
                  width={region.width_milli}
                  height={region.height_milli}
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
        {!region && (
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
        {region && (
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
