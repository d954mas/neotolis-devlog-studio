import { useState } from "preact/hooks";
import type { ExperimentInput, ExperimentResultInput, ResearchReel } from "../../api/research";
import { ExperimentComposer } from "./ExperimentComposer";
import { ExperimentResultForm } from "./ExperimentResultForm";

interface Props {
  reel: ResearchReel;
  experimentBusy: boolean;
  onAuthor: (authorId: string) => void;
  onExperiment: (input: ExperimentInput) => Promise<boolean>;
  onExperimentResult: (experimentId: string, input: ExperimentResultInput) => Promise<boolean>;
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

function compact(value: number): string {
  return new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 }).format(value);
}

function freshness(hours: number): string {
  if (hours < 1) return "updated <1h ago";
  if (hours < 48) return `updated ${Math.round(hours)}h ago`;
  return `updated ${Math.round(hours / 24)}d ago`;
}

function readableText(value: string): string {
  return value
    .replace(/https?:\/\/\S+/g, " ")
    .replace(/(^|\s)#\S+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function reelHeadline(reel: ResearchReel): string {
  const source = readableText(reel.hook || reel.caption);
  if (!source) return "Hook not transcribed yet.";
  const sentence = source.match(/^.{1,140}?[.!?](?:\s|$)/)?.[0]?.trim();
  return sentence || source;
}

function supportingCopy(reel: ResearchReel, headline: string): string {
  const caption = readableText(reel.caption);
  if (!caption) return "";
  if (reel.hook.trim()) return caption === readableText(reel.hook) ? "" : caption;
  return caption.startsWith(headline) ? caption.slice(headline.length).trim() : caption;
}

export function ReelCard({ reel, experimentBusy, onAuthor, onExperiment, onExperimentResult }: Props) {
  const [composing, setComposing] = useState(false);
  const [recordingResult, setRecordingResult] = useState(false);
  const [thumbnailBroken, setThumbnailBroken] = useState(false);
  const experiment = reel.experiment;
  const cardMode = experiment ? ` mode-${experiment.mode}` : "";
  const headline = reelHeadline(reel);
  const notes = supportingCopy(reel, headline);

  return (
    <article class={`research-reel${cardMode}`}>
      <div class="reel-content">
        <div class="reel-byline">
          <button class="author-link" onClick={() => onAuthor(reel.author_id)}>
            @{reel.author.username}
          </button>
          <time dateTime={reel.published_at}>
            {new Date(reel.published_at).toLocaleDateString(undefined, {
              day: "2-digit",
              month: "short",
              year: "numeric",
            })}
          </time>
          {experiment && (
            <span class={`experiment-badge ${experiment.mode}`}>
              ◇ {MODE_LABELS[experiment.mode]}
            </span>
          )}
        </div>

        <h3 class="reel-title" title={headline}>{headline}</h3>

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
              alt={`${headline} — @${reel.author.username}`}
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
        </a>

        {notes && <p class="reel-notes" title={notes}>{notes}</p>}

        <div class="reel-metrics" aria-label="Reel performance">
          <span><b>{compact(reel.views)}</b> views</span>
          <span class={reel.outlier_score && reel.outlier_score >= 2 ? "metric-outlier" : ""}>
            <b>{reel.outlier_score == null ? "—" : `${reel.outlier_score}×`}</b> baseline
          </span>
          <span><b>{compact(reel.likes)}</b> likes</span>
          <span><b>{compact(Math.round(reel.velocity))}</b> / hour</span>
          {reel.growth_views != null && (
            <span class="metric-growth"><b>+{compact(reel.growth_views)}</b> since last check</span>
          )}
        </div>

        <span class="metrics-freshness">{freshness(reel.metrics_age_hours)}</span>

        {reel.patterns.length > 0 && (
          <div class="pattern-list">
            {reel.patterns.map((pattern) => <span key={pattern}>{pattern}</span>)}
          </div>
        )}

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
                  <span>{compact(experiment.result.views)} views · {experiment.result.notes || "No learning notes yet."}</span>
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
      </div>
    </article>
  );
}
