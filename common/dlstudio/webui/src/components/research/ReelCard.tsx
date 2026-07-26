import { useState } from "preact/hooks";
import type { ExperimentInput, ExperimentResultInput, ResearchReel } from "../../api/research";
import { ExperimentComposer } from "./ExperimentComposer";
import { ExperimentResultForm } from "./ExperimentResultForm";
import { ReelMetricsOverlay } from "./ReelMetricsOverlay";
import { ReelMedia } from "./ReelMedia";
import { compactMetric, formatFeedDate, metricFreshness, reelCopy } from "./reel-card-format";

interface Props {
  projectId: string;
  reel: ResearchReel;
  showDate?: boolean;
  experimentBusy: boolean;
  onAuthor: (authorId: string) => void;
  onExperiment: (input: ExperimentInput) => Promise<boolean>;
  onExperimentResult: (experimentId: string, input: ExperimentResultInput) => Promise<boolean>;
  onCacheChange: () => void;
}

const MODE_LABELS = {
  inspiration: "Inspiration",
  adaptation: "Adaptation",
  remake: "Remake",
};

const VERDICT_LABELS = {
  worked: "Worked",
  mixed: "Mixed",
  did_not_work: "Did not work",
  inconclusive: "Inconclusive",
};

export function ReelCard({ projectId, reel, showDate = true, experimentBusy, onAuthor, onExperiment, onExperimentResult, onCacheChange }: Props) {
  const [composing, setComposing] = useState(false);
  const [recordingResult, setRecordingResult] = useState(false);
  const [thumbnailBroken, setThumbnailBroken] = useState(false);
  const experiment = reel.experiment;
  const cardMode = experiment ? ` mode-${experiment.mode}` : "";
  const copy = reelCopy(reel);

  return (
    <article class={`research-reel${cardMode}`}>
      <div class="reel-content">
        <div class="reel-byline">
          <button class="author-link" onClick={() => onAuthor(reel.author_id)}>
            @{reel.author.username}
          </button>
          {showDate && (
            <time dateTime={reel.published_at} title={new Date(reel.published_at).toLocaleString()}>
              {formatFeedDate(reel.published_at)}
            </time>
          )}
          {experiment && (
            <span class={`experiment-badge ${experiment.mode}`}>
              ◇ {MODE_LABELS[experiment.mode]}
            </span>
          )}
        </div>

        <div class="reel-summary">
          <a
            class="reel-visual"
            href={reel.url}
            target="_blank"
            rel="noreferrer"
            aria-label={`Open Reel by @${reel.author.username}`}
          >
            {reel.thumbnail_url && !thumbnailBroken ? (
              <img
                src={reel.thumbnail_url}
                alt={`${copy.title} — @${reel.author.username}`}
                loading="lazy"
                referrerPolicy="no-referrer"
                onError={() => setThumbnailBroken(true)}
              />
            ) : (
              <span class="reel-placeholder" aria-hidden="true">▶</span>
            )}
            <span class="reel-type">Reel</span>
            {reel.duration_seconds != null && (
              <span class="reel-duration">{Math.round(reel.duration_seconds)}s</span>
            )}
            <ReelMetricsOverlay reel={reel} />
          </a>

          <div class="reel-copy">
            <span class="reel-copy-label">{copy.label}</span>
            <h3 class="reel-title" title={copy.title}>{copy.title}</h3>
            {copy.description && (
              <p class="reel-notes" title={copy.description}>{copy.description}</p>
            )}
            {reel.growth_views != null && (
              <span class="reel-growth">+{compactMetric(reel.growth_views)} since last check</span>
            )}
            {reel.patterns.length > 0 && (
              <div class="pattern-list">
                {reel.patterns.map((pattern) => <span key={pattern}>{pattern}</span>)}
              </div>
            )}
            <span class="metrics-freshness">{metricFreshness(reel.metrics_age_hours)}</span>
          </div>
        </div>

        {experiment ? (
          recordingResult ? (
            <ExperimentResultForm
              experiment={experiment}
              busy={experimentBusy}
              onCancel={() => setRecordingResult(false)}
              onSave={async (input) => {
                const saved = await onExperimentResult(experiment.id, input);
                if (saved) setRecordingResult(false);
                return saved;
              }}
            />
          ) : (
            <div class="experiment-summary">
              <span class="eyebrow">Learning hypothesis</span>
              <p>{experiment.hypothesis || "Hypothesis has not been written yet."}</p>
              <div class="experiment-boundaries">
                <div><b>Borrow</b><span>{experiment.take_from_reference.join(" · ") || "Not specified"}</span></div>
                <div><b>Keep ours</b><span>{experiment.keep_original.join(" · ") || "Project voice and visual style"}</span></div>
              </div>
              {experiment.result ? (
                <div class={`experiment-result ${experiment.result.verdict}`}>
                  <b>{VERDICT_LABELS[experiment.result.verdict]}</b>
                  <span>{compactMetric(experiment.result.views)} views · {experiment.result.notes || "No learning notes yet."}</span>
                </div>
              ) : (
                <button class="btn sm secondary" onClick={() => setRecordingResult(true)}>Record our result</button>
              )}
              <code>{experiment.agent_context_path}</code>
            </div>
          )
        ) : composing ? (
          <ExperimentComposer
            reel={reel}
            busy={experimentBusy}
            onCancel={() => setComposing(false)}
            onCreate={onExperiment}
          />
        ) : (
          <div class="reel-actions">
            <a class="btn sm secondary" href={reel.url} target="_blank" rel="noreferrer">Open Reel</a>
            <button class="btn sm" onClick={() => setComposing(true)}>Create experiment</button>
          </div>
        )}
        <ReelMedia projectId={projectId} reel={reel} onCacheChange={onCacheChange} />
      </div>
    </article>
  );
}
