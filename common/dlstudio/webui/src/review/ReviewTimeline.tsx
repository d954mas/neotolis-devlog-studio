import type {
  FrameSelection,
  ReviewContext,
  ReviewFindingBody,
  ReviewTimelineItem,
} from "./types";
import { frameCount, formatTimecode, nsToFrameCeil } from "./types";

type ReviewTimelineProps = {
  context: ReviewContext;
  currentFrame: number;
  selection: FrameSelection;
  activeTargets: string[];
  findings: ReviewFindingBody[];
  onSeek: (frame: number) => void;
  onSelectFinding: (finding: ReviewFindingBody) => void;
};

function laneLabel(lane: string): string {
  if (lane.startsWith("layer.")) return `Слой ${lane.slice(6)}`;
  if (lane.startsWith("audio.")) {
    const role = lane.slice(6);
    const labels: Record<string, string> = {
      voice: "Голос",
      music: "Музыка",
      sfx: "Звуковые эффекты",
      ambient: "Атмосфера",
    };
    return labels[role] ?? "Звук";
  }
  if (lane === "transitions") return "Переходы";
  return lane;
}

function orderedLanes(items: ReviewTimelineItem[]): string[] {
  return Array.from(new Set(items.map((item) => item.lane))).sort(
    (first, second) => {
      if (first.startsWith("layer.") && second.startsWith("layer.")) {
        return Number(second.slice(6)) - Number(first.slice(6));
      }
      if (first.startsWith("layer.")) return -1;
      if (second.startsWith("layer.")) return 1;
      if (first === "transitions") return -1;
      if (second === "transitions") return 1;
      return first.localeCompare(second);
    },
  );
}

export function ReviewTimeline({
  context,
  currentFrame,
  selection,
  activeTargets,
  findings,
  onSeek,
  onSelectFinding,
}: ReviewTimelineProps) {
  const totalFrames = frameCount(context);
  const lanes = orderedLanes(context.items);
  const percent = (frame: number) => `${(frame / totalFrames) * 100}%`;

  return (
    <section class="review-timeline" aria-labelledby="timeline-title">
      <div class="review-section-head">
        <div>
          <p class="label">Структура финального TimelineIR</p>
          <h3 id="timeline-title">Слои, переходы и звук</h3>
        </div>
        <p>Затронутые элементы прикладываются к комментарию автоматически</p>
      </div>
      <div class="timeline-board">
        <div class="timeline-ruler">
          <span />
          <div>
            {[0, 0.25, 0.5, 0.75, 1].map((part) => {
              const frame = Math.min(
                totalFrames - 1,
                Math.round((totalFrames - 1) * part),
              );
              return (
                <button
                  type="button"
                  key={part}
                  style={{ left: `${part * 100}%` }}
                  onClick={() => onSeek(frame)}
                >
                  F{frame}
                </button>
              );
            })}
          </div>
        </div>
        <div class="timeline-content">
          <div class="timeline-track-overlay" aria-hidden="true">
            <div
              class="selection-band"
              style={{
                left: percent(selection.startFrame),
                width: percent(
                  selection.endFrameExclusive - selection.startFrame,
                ),
              }}
            />
            <div
              class="playhead"
              style={{ left: percent(currentFrame) }}
            />
          </div>
          {lanes.map((lane) => (
            <div class="timeline-lane" key={lane}>
              <strong>{laneLabel(lane)}</strong>
              <div>
                {context.items
                  .filter((item) => item.lane === lane)
                  .map((item) => {
                    const start = Math.max(
                      0,
                      Math.min(
                        totalFrames - 1,
                        nsToFrameCeil(item.start_ns, context),
                      ),
                    );
                    const end = Math.max(
                      start + 1,
                      Math.min(
                        totalFrames,
                        nsToFrameCeil(
                          item.start_ns + item.duration_ns,
                          context,
                        ),
                      ),
                    );
                    const duration = end - start;
                    const active = activeTargets.includes(item.item_id);
                    return (
                      <button
                        type="button"
                        key={item.item_id}
                        class={`timeline-item ${item.kind} ${
                          active ? "selected" : ""
                        }`}
                        style={{
                          left: percent(start),
                          width: percent(duration),
                        }}
                        title={`Перейти к началу: ${item.label}`}
                        aria-current={active ? "true" : undefined}
                        onClick={() => onSeek(start)}
                      >
                        <span>{item.label}</span>
                      </button>
                    );
                  })}
              </div>
            </div>
          ))}
          <div class="timeline-lane comment-lane">
            <strong>Замечания</strong>
            <div>
              {findings.map((finding, index) => {
                const start = finding.locator?.start_frame ?? 0;
                return (
                  <button
                    type="button"
                    class="comment-marker"
                    key={finding.finding_id}
                    style={{ left: percent(start) }}
                    onClick={() => onSelectFinding(finding)}
                    title={finding.text}
                    aria-label={`Замечание ${index + 1}, кадр ${start}, ${
                      formatTimecode(start, context)
                    }: ${finding.text}`}
                  >
                    {index + 1}
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
