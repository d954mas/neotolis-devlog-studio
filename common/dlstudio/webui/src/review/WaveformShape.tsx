import { useMemo } from "preact/hooks";

type WaveformShapeProps = {
  peaksMilli: readonly number[];
  noAudio?: boolean;
  className?: string;
};

const VIEWBOX_WIDTH = 1000;
const VIEWBOX_HEIGHT = 100;
const CENTER_Y = VIEWBOX_HEIGHT / 2;
const MAX_AMPLITUDE = 48;

function clampPeak(value: number): number {
  return Number.isFinite(value) ? Math.max(0, Math.min(1000, value)) : 0;
}

function waveformPath(peaksMilli: readonly number[], flat: boolean): string {
  if (flat || peaksMilli.length === 0) {
    return `M 0 ${CENTER_Y} L ${VIEWBOX_WIDTH} ${CENTER_Y}`;
  }

  const lastIndex = peaksMilli.length - 1;
  const xFor = (index: number) =>
    lastIndex === 0 ? VIEWBOX_WIDTH / 2 : (index / lastIndex) * VIEWBOX_WIDTH;
  const amplitudeFor = (peak: number) =>
    (clampPeak(peak) / 1000) * MAX_AMPLITUDE;

  const upper = peaksMilli.map(
    (peak, index) =>
      `${index === 0 ? "M" : "L"} ${xFor(index)} ${
        CENTER_Y - amplitudeFor(peak)
      }`,
  );
  const lower = [...peaksMilli]
    .reverse()
    .map((peak, reverseIndex) => {
      const index = lastIndex - reverseIndex;
      return `L ${xFor(index)} ${CENTER_Y + amplitudeFor(peak)}`;
    });
  return `${upper.join(" ")} ${lower.join(" ")} Z`;
}

export function WaveformShape({
  peaksMilli,
  noAudio = false,
  className,
}: WaveformShapeProps) {
  const flat = noAudio || peaksMilli.length === 0;
  const path = useMemo(
    () => waveformPath(peaksMilli, flat),
    [flat, peaksMilli],
  );
  const classes = [
    "review-waveform-shape",
    flat ? "is-no-audio" : "",
    className ?? "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <svg
      class={classes}
      viewBox={`0 0 ${VIEWBOX_WIDTH} ${VIEWBOX_HEIGHT}`}
      preserveAspectRatio="none"
      aria-hidden="true"
      focusable="false"
    >
      <path
        class="review-waveform-path"
        d={path}
        fill={flat ? "none" : "currentColor"}
        stroke={flat ? "currentColor" : "none"}
        stroke-width={flat ? 1 : undefined}
        vector-effect="non-scaling-stroke"
      />
    </svg>
  );
}
