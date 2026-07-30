import type {
  FrameSelection,
  ResolutionDraft,
  ResolutionStatus,
  ReviewContext,
  ReviewFindingBody,
  ReviewRegion,
  ReviewTimelineItem,
} from "./types";
import { useRef } from "preact/hooks";
import { formatSelection } from "./types";

type ReviewNotesProps = {
  context: ReviewContext;
  selection: FrameSelection;
  region: ReviewRegion | null;
  activeTargets: string[];
  findings: ReviewFindingBody[];
  previousFindings: ReviewFindingBody[];
  resolutionDrafts: Record<string, ResolutionDraft>;
  note: string;
  submitting: boolean;
  onNote: (value: string) => void;
  onAdd: () => void;
  onRemove: (findingId: string) => void;
  onSelect: (finding: ReviewFindingBody) => void;
  onResolve: (
    findingId: string,
    status: ResolutionStatus,
    currentFindingId?: string | null,
  ) => void;
  onResolveAll: () => void;
  onSubmit: (outcome: "pass" | "changes_requested") => void;
};

function targetLabel(
  targetId: string,
  items: ReviewTimelineItem[],
): string {
  const item = items.find((candidate) => candidate.item_id === targetId);
  if (!item) return targetId;
  if (item.kind === "audio") {
    const role = item.lane.slice("audio.".length);
    const labels: Record<string, string> = {
      voice: "Голос",
      music: "Музыка",
      sfx: "Звуковой эффект",
      ambient: "Атмосфера",
    };
    return labels[role] ?? "Звук";
  }
  if (item.kind === "transition") {
    const labels: Record<string, string> = {
      fade: "Плавный переход",
      "fade in": "Появление",
      "fade out": "Затемнение",
      "dip black": "Переход через чёрный",
      "slide left": "Сдвиг влево",
      "slide right": "Сдвиг вправо",
    };
    return labels[item.label] ?? "Переход";
  }
  if (item.label.startsWith("solid ")) {
    return item.z === 0 ? "Фон" : "Графический слой";
  }
  return item.label;
}

export function ReviewNotes({
  context,
  selection,
  region,
  activeTargets,
  findings,
  previousFindings,
  resolutionDrafts,
  note,
  submitting,
  onNote,
  onAdd,
  onRemove,
  onSelect,
  onResolve,
  onResolveAll,
  onSubmit,
}: ReviewNotesProps) {
  const noteRef = useRef<HTMLTextAreaElement>(null);
  const hasUnsavedNote = note.trim().length > 0;

  function saveFinding() {
    onAdd();
    requestAnimationFrame(() => noteRef.current?.focus());
  }

  function removeFinding(findingId: string) {
    onRemove(findingId);
    requestAnimationFrame(() => noteRef.current?.focus());
  }

  return (
    <aside class="review-notes" aria-labelledby="notes-title">
      <div>
        <p class="label">Комментарий к этому моменту</p>
        <h3 id="notes-title">Что изменить?</h3>
      </div>
      {previousFindings.length > 0 && (
        <section
          class="resolution-review"
          aria-labelledby="resolution-title"
        >
          <div class="resolution-head">
            <div>
              <p class="label">Прошлый раунд</p>
              <h3 id="resolution-title">Что стало с замечаниями?</h3>
            </div>
            <button type="button" class="quiet" onClick={onResolveAll}>
              Все исправлены
            </button>
          </div>
          <ol>
            {previousFindings.map((finding) => {
              const draft = resolutionDrafts[finding.finding_id] ?? {
                status: "unresolved",
                currentFindingId: null,
              };
              return (
                <li key={finding.finding_id}>
                  <p>{finding.text}</p>
                  <select
                    value={draft.status}
                    disabled={submitting}
                    aria-label={`Результат: ${finding.text}`}
                    onInput={(event) =>
                      onResolve(
                        finding.finding_id,
                        event.currentTarget.value as ResolutionStatus,
                      )
                    }
                  >
                    <option value="unresolved">Выберите результат</option>
                    <option value="fixed">Исправлено</option>
                    <option value="still_wrong">Всё ещё не так</option>
                    <option value="obsolete">Больше не актуально</option>
                  </select>
                  {draft.status === "still_wrong" && (
                    <select
                      value={draft.currentFindingId ?? ""}
                      disabled={submitting}
                      aria-label={`Новый комментарий: ${finding.text}`}
                      onInput={(event) =>
                        onResolve(
                          finding.finding_id,
                          "still_wrong",
                          event.currentTarget.value || null,
                        )
                      }
                    >
                      <option value="">Выберите новый комментарий</option>
                      {findings.map((current) => (
                        <option
                          key={current.finding_id}
                          value={current.finding_id}
                        >
                          {current.text}
                        </option>
                      ))}
                    </select>
                  )}
                </li>
              );
            })}
          </ol>
        </section>
      )}
      <div class="locator-summary">
        <strong>{formatSelection(selection, context)}</strong>
        <span>{region ? "Есть область в кадре" : "Весь кадр"}</span>
        {activeTargets.slice(0, 3).map((target) => (
          <span class="target-chip" key={target}>
            {targetLabel(target, context.items)}
          </span>
        ))}
        {activeTargets.length > 3 && (
          <span class="target-chip">+{activeTargets.length - 3}</span>
        )}
        {activeTargets.length > 0 && (
          <small>Слои приложатся автоматически</small>
        )}
      </div>
      <label class="note-field">
        Комментарий
        <textarea
          ref={noteRef}
          value={note}
          disabled={submitting}
          onInput={(event) => onNote(event.currentTarget.value)}
          placeholder="Например: переход слишком резкий, а музыка перекрывает фразу"
        />
      </label>
      <button
        type="button"
        class="primary add-note"
        disabled={submitting || !hasUnsavedNote}
        onClick={saveFinding}
      >
        Сохранить комментарий
      </button>

      <div class="finding-list">
        <div class="finding-list-head" role="status" aria-live="polite">
          <strong>Сохранено на этом устройстве</strong>
          <span>{findings.length}</span>
        </div>
        {findings.length === 0 ? (
          <p class="empty-findings">
            Остановите видео на проблемном месте и напишите, что не так.
          </p>
        ) : (
          <ol>
            {findings.map((finding, index) => (
              <li key={finding.finding_id}>
                <button
                  type="button"
                  class="finding-jump"
                  onClick={() => onSelect(finding)}
                >
                  <span>{String(index + 1).padStart(2, "0")}</span>
                  <strong>
                    {finding.locator
                      ? formatSelection(
                          {
                            startFrame: finding.locator.start_frame,
                            endFrameExclusive:
                              finding.locator.end_frame_exclusive,
                          },
                          context,
                        )
                      : "Общее замечание"}
                  </strong>
                  <p>{finding.text}</p>
                  {finding.locator && (
                    <div class="finding-meta">
                      {finding.locator.region && <span>Область</span>}
                      {(finding.locator.target_ids ?? []).map((target) => (
                        <span key={target}>
                          {targetLabel(target, context.items)}
                        </span>
                      ))}
                    </div>
                  )}
                </button>
                <button
                  type="button"
                  class="remove-finding"
                  disabled={submitting}
                  onClick={() => removeFinding(finding.finding_id)}
                  aria-label={`Удалить замечание ${index + 1}`}
                >
                  ×
                </button>
              </li>
            ))}
          </ol>
        )}
      </div>

      <div class="review-note-actions">
        <p>
          {hasUnsavedNote
            ? "Сначала сохраните написанный комментарий."
            : findings.length === 0
            ? "Можно одобрить версию или добавить комментарий."
            : `Готово к отправке: ${findings.length}`}
        </p>
        <div>
          <button
            type="button"
            class="quiet"
            disabled={submitting || findings.length > 0 || hasUnsavedNote}
            onClick={() => onSubmit("pass")}
          >
            Всё устраивает
          </button>
          <button
            type="button"
            class="primary"
            disabled={
              submitting || findings.length === 0 || hasUnsavedNote
            }
            onClick={() => onSubmit("changes_requested")}
          >
            {submitting
              ? "Отправляю…"
              : `Отправить комментарии · ${findings.length}`}
          </button>
        </div>
      </div>
    </aside>
  );
}
