import type {
  FrameSelection,
  ReviewContext,
  ReviewFindingBody,
  ReviewRegion,
} from "./types";
import { useEffect, useRef } from "preact/hooks";
import { formatSelection, targetLabel } from "./types";

export type ResolutionSummary = {
  total: number;
  fixed: number;
  stillWrong: number;
  obsolete: number;
  pending: number;
};

type ReviewNotesProps = {
  context: ReviewContext;
  selection: FrameSelection;
  region: ReviewRegion | null;
  activeTargets: string[];
  findings: ReviewFindingBody[];
  resolutionSummary: ResolutionSummary;
  pendingPreviousText: string | null;
  focusComposerToken: number;
  note: string;
  submitting: boolean;
  readOnly: boolean;
  reviewReady: boolean;
  onNote: (value: string) => void;
  onAdd: () => void;
  onRemove: (findingId: string) => void;
  onSelect: (finding: ReviewFindingBody) => void;
  onSubmit: (outcome: "pass" | "changes_requested") => void;
};

export function ReviewNotes({
  context,
  selection,
  region,
  activeTargets,
  findings,
  resolutionSummary,
  pendingPreviousText,
  focusComposerToken,
  note,
  submitting,
  readOnly,
  reviewReady,
  onNote,
  onAdd,
  onRemove,
  onSelect,
  onSubmit,
}: ReviewNotesProps) {
  const noteRef = useRef<HTMLTextAreaElement>(null);
  const hasUnsavedNote = note.trim().length > 0;

  useEffect(() => {
    if (
      focusComposerToken > 0 &&
      window.matchMedia("(min-width: 901px)").matches
    ) {
      noteRef.current?.focus();
    }
  }, [focusComposerToken]);

  function saveFinding() {
    onAdd();
    requestAnimationFrame(() => noteRef.current?.focus());
  }

  function removeFinding(findingId: string) {
    onRemove(findingId);
    requestAnimationFrame(() => noteRef.current?.focus());
  }

  return (
    <aside
      class={`review-notes ${readOnly ? "read-only" : ""}`}
      aria-labelledby="notes-title"
    >
      <div>
        <p class="label">
          {readOnly ? "Прошлая версия" : "Комментарий к этому моменту"}
        </p>
        <h3 id="notes-title">
          {readOnly ? "Смотрите и слушайте" : "Что изменить?"}
        </h3>
      </div>
      {readOnly && (
        <div class="old-version-lock" role="status" aria-live="polite">
          До · сравнение без разметки. Вернитесь к «Сейчас», чтобы
          оставить комментарий.
        </div>
      )}
      {pendingPreviousText && !readOnly && (
        <div class="continued-finding" role="status">
          <strong>Уточните, что всё ещё не так</strong>
          <p>{pendingPreviousText}</p>
          <small>
            Мы открыли примерно тот же момент. Проверьте диапазон и отметьте
            область заново, если она нужна.
          </small>
        </div>
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
          disabled={submitting || readOnly || !reviewReady}
          onInput={(event) => onNote(event.currentTarget.value)}
          placeholder="Например: переход слишком резкий, а музыка перекрывает фразу"
        />
      </label>
      <button
        type="button"
        class="primary add-note"
        disabled={
          submitting || readOnly || !reviewReady || !hasUnsavedNote
        }
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
                  disabled={readOnly}
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
                  disabled={submitting || readOnly}
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
          {readOnly
            ? "Версия «До» открыта только для сравнения."
            : !reviewReady
            ? "Сначала загрузится точное видео и данные сравнения."
            : hasUnsavedNote
            ? "Сначала сохраните написанный комментарий."
            : findings.length === 0
            ? resolutionSummary.total > 0
              ? `${resolutionSummary.fixed} исправлено · ${resolutionSummary.obsolete} неактуально`
              : "Можно одобрить версию или добавить комментарий."
            : `${findings.length} новых · ${resolutionSummary.fixed} исправлено · ${resolutionSummary.obsolete} неактуально`}
        </p>
        <div>
          <button
            type="button"
            class="quiet"
            disabled={
              submitting ||
              readOnly ||
              !reviewReady ||
              findings.length > 0 ||
              hasUnsavedNote ||
              resolutionSummary.pending > 0 ||
              resolutionSummary.stillWrong > 0
            }
            onClick={() => onSubmit("pass")}
          >
            {resolutionSummary.total > 0
              ? resolutionSummary.obsolete > 0
                ? `Подтвердить: ${resolutionSummary.fixed} исправлено`
                : "Подтвердить: всё исправлено"
              : "Всё устраивает"}
          </button>
          <button
            type="button"
            class="primary"
            disabled={
              submitting ||
              readOnly ||
              !reviewReady ||
              findings.length === 0 ||
              hasUnsavedNote ||
              resolutionSummary.pending > 0
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
