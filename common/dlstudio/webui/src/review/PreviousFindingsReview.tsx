import type { JSX } from "preact";
import { useEffect, useRef } from "preact/hooks";
import type {
  ResolutionDraft,
  ReviewFindingBody,
  ReviewTaskPack,
} from "./types";
import { FindingRegionEvidence } from "./FindingRegionEvidence";
import { formatSelection, targetLabel } from "./types";

export type PreviousPackState =
  | "loading"
  | "ready"
  | "unavailable"
  | "mismatch";

type PreviousFindingsReviewProps = {
  pack: ReviewTaskPack | null;
  packState: PreviousPackState;
  finding: ReviewFindingBody;
  index: number;
  total: number;
  draft: ResolutionDraft;
  currentFinding: ReviewFindingBody | null;
  pendingCapture: boolean;
  showingOld: boolean;
  sameMedia: boolean;
  submitting: boolean;
  reviewReady: boolean;
  navigationLocked: boolean;
  onPrevious: () => void;
  onNext: () => void;
  onShowOld: (showing: boolean) => void;
  onStillWrong: () => void;
  onObsolete: () => void;
  onDefaultFixed: () => void;
  onOpenCurrentFinding: () => void;
  onRetry: () => void;
};

const HOLD_THRESHOLD_MS = 320;

export function PreviousFindingsReview({
  pack,
  packState,
  finding,
  index,
  total,
  draft,
  currentFinding,
  pendingCapture,
  showingOld,
  sameMedia,
  submitting,
  reviewReady,
  navigationLocked,
  onPrevious,
  onNext,
  onShowOld,
  onStillWrong,
  onObsolete,
  onDefaultFixed,
  onOpenCurrentFinding,
  onRetry,
}: PreviousFindingsReviewProps) {
  const titleRef = useRef<HTMLHeadingElement>(null);
  const pressStartedAt = useRef(0);
  const pressStartedOld = useRef(false);
  const pointerActive = useRef(false);
  const keyboardKey = useRef<string | null>(null);
  const suppressClick = useRef(false);

  useEffect(() => {
    titleRef.current?.focus();
  }, [finding.finding_id]);

  useEffect(() => {
    function cancelActivePreview() {
      if (pointerActive.current || keyboardKey.current !== null) {
        pointerActive.current = false;
        keyboardKey.current = null;
        onShowOld(pressStartedOld.current);
      }
      suppressClick.current = false;
    }
    function handleVisibilityChange() {
      if (document.visibilityState !== "visible") {
        cancelActivePreview();
      }
    }
    window.addEventListener("blur", cancelActivePreview);
    document.addEventListener(
      "visibilitychange",
      handleVisibilityChange,
    );
    return () => {
      window.removeEventListener("blur", cancelActivePreview);
      document.removeEventListener(
        "visibilitychange",
        handleVisibilityChange,
      );
      cancelActivePreview();
    };
  }, [onShowOld]);

  function startOldPreview() {
    pressStartedAt.current = performance.now();
    pressStartedOld.current = showingOld;
    onShowOld(true);
  }

  function finishOldPreview() {
    const held =
      performance.now() - pressStartedAt.current >= HOLD_THRESHOLD_MS;
    onShowOld(held ? pressStartedOld.current : !pressStartedOld.current);
  }

  function cancelOldPreview() {
    onShowOld(pressStartedOld.current);
  }

  function handlePointerDown(
    event: JSX.TargetedPointerEvent<HTMLButtonElement>,
  ) {
    if (event.button !== 0) return;
    pointerActive.current = true;
    event.currentTarget.setPointerCapture(event.pointerId);
    startOldPreview();
  }

  function handlePointerUp(
    event: JSX.TargetedPointerEvent<HTMLButtonElement>,
  ) {
    if (!pointerActive.current) return;
    pointerActive.current = false;
    finishOldPreview();
    suppressClick.current = true;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  }

  function handlePointerCancel() {
    if (!pointerActive.current) return;
    pointerActive.current = false;
    cancelOldPreview();
  }

  function handleKeyDown(
    event: JSX.TargetedKeyboardEvent<HTMLButtonElement>,
  ) {
    if (
      event.repeat ||
      keyboardKey.current !== null ||
      (event.key !== " " && event.key !== "Enter")
    ) {
      return;
    }
    event.preventDefault();
    keyboardKey.current = event.key;
    startOldPreview();
  }

  function handleKeyUp(
    event: JSX.TargetedKeyboardEvent<HTMLButtonElement>,
  ) {
    if (event.key !== keyboardKey.current) return;
    event.preventDefault();
    keyboardKey.current = null;
    finishOldPreview();
    suppressClick.current = true;
  }

  function cancelKeyboardPreview() {
    if (keyboardKey.current === null) return;
    keyboardKey.current = null;
    cancelOldPreview();
  }

  const locator = finding.locator;
  const oldTargets =
    pack === null || locator == null
      ? []
      : (locator.target_ids ?? []).map((targetId) => ({
          id: targetId,
          label: targetLabel(targetId, pack.target_snapshots),
        }));
  const ready = packState === "ready" && pack !== null;
  const statusLabel =
    draft.status === "still_wrong"
      ? "Всё ещё не так"
      : draft.status === "obsolete"
        ? "Больше не актуально"
        : "Исправлено";

  return (
    <section
      class="previous-review"
      aria-labelledby="previous-finding-title"
    >
      <div class="previous-review-topline">
        <div>
          <p class="label">Прошлое замечание</p>
          <h3
            id="previous-finding-title"
            ref={titleRef}
            tabIndex={-1}
          >
            Замечание {index + 1} из {total}
          </h3>
        </div>
        <div class="previous-navigation" aria-label="Прошлые замечания">
          <button
            type="button"
            class="quiet"
            disabled={submitting || total < 2 || navigationLocked}
            onClick={onPrevious}
            aria-label="Предыдущее замечание"
          >
            ←
          </button>
          <button
            type="button"
            class="quiet"
            disabled={submitting || total < 2 || navigationLocked}
            onClick={onNext}
            aria-label="Следующее замечание"
          >
            →
          </button>
        </div>
      </div>

      <blockquote>{finding.text}</blockquote>

      <div class="previous-finding-meta">
        {ready && locator ? (
          <strong>
            Было:{" "}
            {formatSelection(
              {
                startFrame: locator.start_frame,
                endFrameExclusive: locator.end_frame_exclusive,
              },
              pack,
            )}
          </strong>
        ) : (
          <strong>Точная прошлая версия загружается…</strong>
        )}
        {locator?.region && <span>Область в кадре</span>}
        {oldTargets.map((target) => (
          <span key={target.id}>{target.label}</span>
        ))}
      </div>

      {ready && locator?.region && (
        <FindingRegionEvidence
          key={finding.finding_id}
          pack={pack}
          finding={finding}
        />
      )}

      {packState === "mismatch" || packState === "unavailable" ? (
        <div class="previous-pack-error" role="alert">
          <p>
            Прошлая версия изменилась во время загрузки. Сравнение и
            подтверждение временно недоступны.
          </p>
          <button type="button" class="quiet" onClick={onRetry}>
            Обновить review
          </button>
        </div>
      ) : (
        <>
          <div class="version-switch" role="group" aria-label="Версия видео">
            <button
              type="button"
              class={showingOld ? "quiet" : "primary"}
              disabled={!ready || submitting}
              aria-pressed={!showingOld}
              onClick={() => onShowOld(false)}
            >
              Сейчас
            </button>
            <button
              type="button"
              class={showingOld ? "primary" : "quiet"}
              disabled={!ready || locator == null || submitting}
              aria-pressed={showingOld}
              onPointerDown={handlePointerDown}
              onPointerUp={handlePointerUp}
              onPointerCancel={handlePointerCancel}
              onLostPointerCapture={handlePointerCancel}
              onKeyDown={handleKeyDown}
              onKeyUp={handleKeyUp}
              onBlur={() => {
                handlePointerCancel();
                cancelKeyboardPreview();
              }}
              onClick={(event) => {
                event.preventDefault();
                if (suppressClick.current) {
                  suppressClick.current = false;
                  return;
                }
                onShowOld(!showingOld);
              }}
            >
              До исправления
            </button>
          </div>
          <p class="version-switch-hint">
            Удерживайте «До» для быстрого сравнения.
          </p>
          {sameMedia && (
            <p class="same-media-note">
              Видео совпадает с прошлой версией.
            </p>
          )}
        </>
      )}

      {(draft.status !== "unresolved" ||
        pendingCapture ||
        currentFinding) && (
        <div class={`resolution-summary status-${draft.status}`}>
          <span>{statusLabel}</span>
          {pendingCapture && (
            <small>Сохраните новый комментарий к текущей версии.</small>
          )}
          {currentFinding && (
            <button
              type="button"
              class="resolution-link"
              onClick={onOpenCurrentFinding}
            >
              Новый комментарий: {currentFinding.text}
            </button>
          )}
        </div>
      )}

      <div
        class="resolution-exceptions"
        role="group"
        aria-label={`Результат: ${finding.text}`}
      >
        <button
          type="button"
          class={draft.status === "still_wrong" ? "active" : ""}
          disabled={!ready || !reviewReady || submitting || showingOld}
          aria-pressed={draft.status === "still_wrong"}
          onClick={onStillWrong}
        >
          Всё ещё не так
        </button>
        <button
          type="button"
          class={draft.status === "obsolete" ? "active" : ""}
          disabled={!ready || !reviewReady || submitting || showingOld}
          aria-pressed={draft.status === "obsolete"}
          onClick={onObsolete}
        >
          Больше не актуально
        </button>
        {draft.status !== "unresolved" && (
          <button
            type="button"
            class="quiet"
            disabled={!reviewReady || submitting || showingOld}
            onClick={onDefaultFixed}
          >
            Считать исправленным
          </button>
        )}
      </div>
    </section>
  );
}
