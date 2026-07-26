import type { ResearchReel } from "../../api/research";
import { compactMetric } from "./reel-card-format";

type IconKind = "views" | "baseline" | "likes" | "velocity";

function MetricIcon({ kind }: { kind: IconKind }) {
  if (kind === "views") {
    return (
      <svg viewBox="0 0 20 20" aria-hidden="true">
        <path d="M2.2 10s2.8-4.6 7.8-4.6 7.8 4.6 7.8 4.6-2.8 4.6-7.8 4.6S2.2 10 2.2 10Z" />
        <circle cx="10" cy="10" r="2.2" />
      </svg>
    );
  }
  if (kind === "baseline") {
    return (
      <svg viewBox="0 0 20 20" aria-hidden="true">
        <path d="m3 14 4.2-4.2 3 3L17 6" />
        <path d="M12.5 6H17v4.5" />
      </svg>
    );
  }
  if (kind === "likes") {
    return (
      <svg viewBox="0 0 20 20" aria-hidden="true">
        <path d="M10 16.3 3.7 10A3.7 3.7 0 0 1 9 4.8L10 6l1-1.2A3.7 3.7 0 0 1 16.3 10L10 16.3Z" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <path d="m11.2 2.8-6 8.2h4.6l-1 6.2 6-8.3h-4.6l1-6.1Z" />
    </svg>
  );
}

function MetricChip({ kind, value, label }: { kind: IconKind; value: string; label: string }) {
  return (
    <span class={`reel-metric-chip metric-${kind}`} title={`${value} ${label}`}>
      <MetricIcon kind={kind} />
      <b>{value}</b>
      <span class="sr-only"> {label}</span>
    </span>
  );
}

export function ReelMetricsOverlay({ reel }: { reel: ResearchReel }) {
  return (
    <div class="reel-metric-overlay" aria-label="Reel performance">
      <MetricChip kind="views" value={compactMetric(reel.views)} label="views" />
      <MetricChip
        kind="baseline"
        value={reel.outlier_score == null ? "—" : `${reel.outlier_score}×`}
        label="baseline"
      />
      <MetricChip kind="likes" value={compactMetric(reel.likes)} label="likes" />
      <MetricChip
        kind="velocity"
        value={`${compactMetric(Math.round(reel.velocity))}/h`}
        label="views per hour"
      />
    </div>
  );
}
