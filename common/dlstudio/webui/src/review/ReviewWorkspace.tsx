import type { RefObject } from "preact";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "preact/hooks";
import { studioV3 } from "../api/v3.client";
import { FrameStrip } from "./FrameStrip";
import { ReviewNotes } from "./ReviewNotes";
import { ReviewPlayer } from "./ReviewPlayer";
import { ReviewTimeline } from "./ReviewTimeline";
import type {
  FrameSelection,
  ResolutionDraft,
  ResolutionStatus,
  ReviewContext,
  ReviewFindingBody,
  ReviewRegion,
  WorkflowStatus,
} from "./types";
import { clampFrame, frameToSeconds, nsToFrameCeil } from "./types";

type ReviewWorkspaceProps = {
  onError: (message: string | null) => void;
  onSubmitted: (status: WorkflowStatus) => void;
};

function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  if (typeof error === "string") return error;
  return JSON.stringify(error);
}

function isDraftFinding(value: unknown): value is ReviewFindingBody {
  if (typeof value !== "object" || value === null) return false;
  const finding = value as Partial<ReviewFindingBody>;
  if (
    typeof finding.finding_id !== "string" ||
    typeof finding.text !== "string" ||
    typeof finding.requires_change !== "boolean"
  ) {
    return false;
  }
  const locator = finding.locator;
  if (locator === undefined || locator === null) return true;
  return (
    Number.isSafeInteger(locator.start_frame) &&
    Number.isSafeInteger(locator.end_frame_exclusive) &&
    (locator.target_ids === undefined ||
      (Array.isArray(locator.target_ids) &&
        locator.target_ids.every((target) => typeof target === "string")))
  );
}

function draftStorageKey(context: ReviewContext): string {
  return [
    "dlstudio.review",
    context.artifact.sha256,
    context.timeline.sha256,
    context.check_report.sha256,
    context.constraints.sha256,
  ].join(".");
}

export function ReviewWorkspace({
  onError,
  onSubmitted,
}: ReviewWorkspaceProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [context, setContext] = useState<ReviewContext | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [currentFrame, setCurrentFrame] = useState(0);
  const [selection, setSelection] = useState<FrameSelection>({
    startFrame: 0,
    endFrameExclusive: 1,
  });
  const [region, setRegion] = useState<ReviewRegion | null>(null);
  const [note, setNote] = useState("");
  const [findings, setFindings] = useState<ReviewFindingBody[]>([]);
  const [resolutionDrafts, setResolutionDrafts] = useState<
    Record<string, ResolutionDraft>
  >({});
  const [loadedDraftKey, setLoadedDraftKey] = useState<string | null>(null);
  const [contextRequest, setContextRequest] = useState(0);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setContext(null);
    async function loadContext() {
      try {
        const result = await studioV3.GET("/api/v3/review/context");
        if (!active) return;
        if (!result.data) {
          onError("Нет данных для ревью.");
        } else {
          setContext(result.data);
        }
      } catch (cause) {
        if (active) onError(errorMessage(cause));
      } finally {
        if (active) setLoading(false);
      }
    }
    void loadContext();
    return () => {
      active = false;
    };
  }, [contextRequest, onError]);

  useEffect(() => {
    if (!context) return;
    const key = draftStorageKey(context);
    try {
      const value = JSON.parse(localStorage.getItem(key) ?? "[]");
      if (Array.isArray(value)) {
        setFindings(value.filter(isDraftFinding));
      }
    } catch {
      localStorage.removeItem(key);
    }
    setLoadedDraftKey(key);
  }, [context]);

  useEffect(() => {
    if (!context) return;
    const key = draftStorageKey(context);
    if (loadedDraftKey !== key) return;
    localStorage.setItem(key, JSON.stringify(findings));
  }, [context, findings, loadedDraftKey]);

  useEffect(() => {
    const required = context?.latest_verdict?.findings.filter(
      (finding) => finding.requires_change,
    );
    setResolutionDrafts(
      Object.fromEntries(
        (required ?? []).map((finding) => [
          finding.finding_id,
          { status: "unresolved", currentFindingId: null },
        ]),
      ),
    );
  }, [context?.latest_round?.sha256, context?.latest_round?.size]);

  const activeTargets = useMemo(() => {
    if (!context) return [];
    return context.items
      .filter((item) => {
        const itemStart = nsToFrameCeil(item.start_ns, context);
        const itemEnd = nsToFrameCeil(
          item.start_ns + item.duration_ns,
          context,
        );
        return (
          itemStart < selection.endFrameExclusive &&
          itemEnd > selection.startFrame
        );
      })
      .map((item) => item.item_id);
  }, [context, selection]);

  if (loading) {
    return (
      <section class="review-loading" aria-busy="true">
        <span />
        <p>Открываю точный финальный артефакт и его TimelineIR…</p>
      </section>
    );
  }
  if (!context) {
    return (
      <section class="review-loading">
        <p>Review context недоступен. Исправьте ошибку выше и обновите экран.</p>
        <button
          type="button"
          class="quiet"
          onClick={() => {
            onError(null);
            setContextRequest((current) => current + 1);
          }}
        >
          Повторить загрузку
        </button>
      </section>
    );
  }

  function seekVideo(frame: number): number | undefined {
    if (!context) return undefined;
    const next = clampFrame(frame, context);
    const video = videoRef.current;
    if (video) {
      video.pause();
      video.currentTime = frameToSeconds(next, context);
    }
    setCurrentFrame(next);
    return next;
  }

  function seek(frame: number) {
    const next = seekVideo(frame);
    if (next === undefined) return;
    setSelection((current) =>
      current.endFrameExclusive === current.startFrame + 1
        ? { startFrame: next, endFrameExclusive: next + 1 }
        : current,
    );
  }

  function selectFrame(frame: number) {
    const next = seekVideo(frame);
    if (next === undefined) return;
    setSelection({
      startFrame: next,
      endFrameExclusive: next + 1,
    });
  }

  function selectTime(next: FrameSelection, focusFrame: number) {
    if (!context) return;
    const first = clampFrame(next.startFrame, context);
    const last = clampFrame(next.endFrameExclusive - 1, context);
    setSelection({
      startFrame: Math.min(first, last),
      endFrameExclusive: Math.max(first, last) + 1,
    });
    seekVideo(focusFrame);
  }

  const handlePlaybackFrame = useCallback((frame: number) => {
    setCurrentFrame(frame);
    setSelection((current) =>
      current.endFrameExclusive === current.startFrame + 1
        ? { startFrame: frame, endFrameExclusive: frame + 1 }
        : current,
    );
  }, []);

  function addFinding() {
    const text = note.trim();
    if (!text) return;
    let sequence = findings.length + 1;
    while (
      findings.some(
        (finding) =>
          finding.finding_id ===
          `studio.ui.${String(sequence).padStart(3, "0")}`,
      )
    ) {
      sequence += 1;
    }
    setFindings((current) => [
      ...current,
      {
        finding_id: `studio.ui.${String(sequence).padStart(3, "0")}`,
        text,
        requires_change: true,
        locator: {
          start_frame: selection.startFrame,
          end_frame_exclusive: selection.endFrameExclusive,
          region,
          target_ids: activeTargets,
        },
      },
    ]);
    setNote("");
    setRegion(null);
  }

  function selectFinding(finding: ReviewFindingBody) {
    const locator = finding.locator;
    if (!locator) return;
    setSelection({
      startFrame: locator.start_frame,
      endFrameExclusive: locator.end_frame_exclusive,
    });
    setRegion(locator.region ?? null);
    seekVideo(locator.start_frame);
  }

  function resolvePrevious(
    findingId: string,
    status: ResolutionStatus,
    currentFindingId: string | null = null,
  ) {
    setResolutionDrafts((current) => ({
      ...current,
      [findingId]: { status, currentFindingId },
    }));
  }

  async function submit(outcome: "pass" | "changes_requested") {
    if (!context) return;
    if (
      context.latest_round !== null &&
      context.latest_verdict === null
    ) {
      onError("Предыдущий review повреждён или ещё не загружен.");
      return;
    }
    const draftKey = draftStorageKey(context);
    const previousFindings =
      context.latest_verdict?.findings.filter(
        (finding) => finding.requires_change,
      ) ?? [];
    const resolutions = [];
    for (const previous of previousFindings) {
      const draft = resolutionDrafts[previous.finding_id];
      let status = draft?.status;
      if (outcome === "pass" && status === "still_wrong") {
        onError(
          "Нельзя одобрить версию, пока замечание отмечено «всё ещё не так».",
        );
        return;
      }
      if (outcome === "pass") {
        if (status === undefined || status === "unresolved") {
          status = "fixed";
        }
      }
      if (!status || status === "unresolved") {
        onError("Укажите результат для каждого прошлого замечания.");
        return;
      }
      const currentFindingId =
        status === "still_wrong" ? draft?.currentFindingId : null;
      if (
        status === "still_wrong" &&
        !findings.some(
          (finding) => finding.finding_id === currentFindingId,
        )
      ) {
        onError(
          "Для «всё ещё не так» выберите новый точный комментарий.",
        );
        return;
      }
      resolutions.push({
        previous_finding_id: previous.finding_id,
        status,
        current_finding_id: currentFindingId ?? null,
      });
    }
    setSubmitting(true);
    onError(null);
    try {
      const result = await studioV3.POST("/api/v3/review", {
        body: {
          expected_artifact: context.artifact,
          expected_timeline: context.timeline,
          expected_check_report: context.check_report,
          expected_constraints: context.constraints,
          expected_latest_round: context.latest_round,
          resolutions,
          outcome,
          scope: ["visual", "audio", "constraints"],
          reviewer: "author",
          reviewed_at: new Date().toISOString(),
          findings: outcome === "pass" ? [] : findings,
        },
      });
      if (result.error || !result.data) {
        if (result.response.status === 409) {
          const statusResult = await studioV3.GET("/api/v3/status");
          if (
            statusResult.data &&
            statusResult.data.action !== "review"
          ) {
            onSubmitted(statusResult.data);
          } else {
            setContextRequest((current) => current + 1);
          }
        }
        onError(
          errorMessage(result.error ?? "Review API returned no status."),
        );
        return;
      }
      localStorage.removeItem(draftKey);
      onSubmitted(result.data);
    } catch (cause) {
      onError(errorMessage(cause));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section class="review-workspace" aria-labelledby="review-title">
      <div class="review-heading">
        <div>
          <h2 id="review-title">Посмотрите и отметьте, что изменить</h2>
          <p class="review-intro">
            Кликните по кадру или протяните диапазон на шкале. Рамкой на
            видео можно показать точную область.
          </p>
        </div>
      </div>

      <div class="review-grid">
        <div class="review-visuals">
          <ReviewPlayer
            context={context}
            currentFrame={currentFrame}
            videoRef={videoRef as RefObject<HTMLVideoElement>}
            region={region}
            onFrame={handlePlaybackFrame}
            onRegion={setRegion}
            onSeek={seek}
          />
          <FrameStrip
            context={context}
            currentFrame={currentFrame}
            selection={selection}
            onSelect={selectTime}
          />
        </div>
        <ReviewNotes
          context={context}
          selection={selection}
          region={region}
          activeTargets={activeTargets}
          findings={findings}
          note={note}
          submitting={submitting}
          previousFindings={
            context.latest_verdict?.findings.filter(
              (finding) => finding.requires_change,
            ) ?? []
          }
          resolutionDrafts={resolutionDrafts}
          onNote={setNote}
          onAdd={addFinding}
          onRemove={(findingId) =>
            setFindings((current) =>
              current.filter(
                (finding) => finding.finding_id !== findingId,
              ),
            )
          }
          onSelect={selectFinding}
          onResolve={resolvePrevious}
          onResolveAll={() =>
            setResolutionDrafts(
              Object.fromEntries(
                (
                  context.latest_verdict?.findings.filter(
                    (finding) => finding.requires_change,
                  ) ?? []
                ).map((finding) => [
                  finding.finding_id,
                  { status: "fixed", currentFindingId: null },
                ]),
              ),
            )
          }
          onSubmit={(outcome) => void submit(outcome)}
        />
      </div>

      <details class="technical-details">
        <summary>
          <span>Слои, переходы и звук</span>
          <small>
            {context.items.length} элементов · технические детали
          </small>
        </summary>
        <ReviewTimeline
          context={context}
          currentFrame={currentFrame}
          selection={selection}
          activeTargets={activeTargets}
          findings={findings}
          onSeek={selectFrame}
          onSelectFinding={selectFinding}
        />
      </details>
    </section>
  );
}
