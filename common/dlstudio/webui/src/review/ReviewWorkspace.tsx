import type { RefObject } from "preact";
import {
  useEffect,
  useMemo,
  useRef,
  useState,
} from "preact/hooks";
import { studioV3 } from "../api/v3.client";
import { FrameStrip } from "./FrameStrip";
import {
  PreviousFindingsReview,
  type PreviousPackState,
} from "./PreviousFindingsReview";
import {
  ReviewNotes,
  type ResolutionSummary,
} from "./ReviewNotes";
import {
  ReviewPlayer,
  type ReviewMediaState,
} from "./ReviewPlayer";
import { ReviewTimeline } from "./ReviewTimeline";
import type {
  FrameSelection,
  ResolutionDraft,
  ResolutionStatus,
  ReviewContext,
  ReviewFindingBody,
  ReviewRegion,
  ReviewTaskPack,
  WorkflowStatus,
} from "./types";
import {
  clampFrame,
  frameToSeconds,
  mapFrameBoundaryByPresentationTime,
  mapFrameByPresentationTime,
  nsToFrameCeil,
  sameBlobRef,
} from "./types";

type ReviewWorkspaceProps = {
  onError: (message: string | null) => void;
  onSubmitted: (status: WorkflowStatus) => void;
};

const DRAFT_STORAGE_WARNING =
  "Черновик останется в этой вкладке, но браузер не смог сохранить его для перезагрузки.";

function removeLocalDraft(key: string): void {
  try {
    localStorage.removeItem(key);
  } catch {
    // Storage can be disabled. The in-memory draft remains usable.
  }
}

function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  if (typeof error === "string") return error;
  return JSON.stringify(error);
}

function evidenceBlobUrl(ref: { sha256: string; size: number }): string {
  return `/api/v3/blobs/${ref.sha256}?size=${ref.size}`;
}

function ReviewEvidence({ context }: { context: ReviewContext }) {
  const [metadataText, setMetadataText] = useState<string | null>(null);
  const [metadataError, setMetadataError] = useState<string | null>(null);
  const report = context.artifact_evidence;
  const metadata = context.publication_evidence.files.find(
    (item) => item.role === "metadata",
  );

  useEffect(() => {
    setMetadataText(null);
    setMetadataError(null);
    if (!metadata) return;
    if (metadata.blob.size > 512 * 1024) {
      setMetadataError("Metadata больше 512 KiB; доступен только exact hash.");
      return;
    }
    const controller = new AbortController();
    void fetch(evidenceBlobUrl(metadata.blob), { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error(`Studio returned ${response.status}.`);
        return response.text();
      })
      .then(setMetadataText)
      .catch((cause: unknown) => {
        if (!controller.signal.aborted) setMetadataError(errorMessage(cause));
      });
    return () => controller.abort();
  }, [metadata?.blob.sha256, metadata?.blob.size]);

  return (
    <section class="review-evidence" aria-labelledby="review-evidence-title">
      <h3 id="review-evidence-title">Exact evidence</h3>
      <div class="review-evidence-groups">
        <article>
          <h4>Видео</h4>
          <p>{report.width} × {report.height} · {(report.duration_ns / 1_000_000_000).toFixed(2)} s · {report.fps_num / report.fps_den} fps</p>
          <code>{context.artifact.sha256}</code>
          <small>{context.artifact.size.toLocaleString()} bytes</small>
        </article>
        <article>
          <h4>Аудио report</h4>
          {report.audio_codec === null ? (
            <p>Аудиопоток отсутствует</p>
          ) : (
            <dl>
              <div><dt>Поток</dt><dd>{report.audio_codec} · {report.audio_sample_rate} Hz · {report.audio_channels} ch</dd></div>
              <div><dt>Громкость</dt><dd>{report.integrated_lufs_milli === null ? "—" : `${(report.integrated_lufs_milli / 1000).toFixed(1)} LUFS`}</dd></div>
              <div><dt>True peak</dt><dd>{report.true_peak_db_milli === null ? "—" : `${(report.true_peak_db_milli / 1000).toFixed(1)} dBTP`}</dd></div>
              <div><dt>Слышимый сигнал</dt><dd>{report.active_audio_ratio_milli === null ? "—" : `${(report.active_audio_ratio_milli / 10).toFixed(1)}%`}</dd></div>
              <div><dt>Voice peak</dt><dd>{report.voice_true_peak_db_milli == null ? "—" : `${(report.voice_true_peak_db_milli / 1000).toFixed(1)} dBFS`}</dd></div>
              <div><dt>Voice active</dt><dd>{report.voice_active_audio_ratio_milli == null ? "—" : `${(report.voice_active_audio_ratio_milli / 10).toFixed(1)}%`}</dd></div>
              <div><dt>Voice in exact final</dt><dd>{report.voice_correlation_db_milli == null ? "—" : `${(report.voice_correlation_db_milli / 1000).toFixed(1)} dB`}</dd></div>
            </dl>
          )}
          <code>{context.artifact_report.sha256}</code>
        </article>
        <article>
          <h4>Publication files</h4>
          {context.publication_evidence.files.map((item) => (
            <div class="publication-evidence" key={item.path}>
              <strong>{item.role}: {item.path}</strong>
              {item.role === "cover" && (
                <img src={evidenceBlobUrl(item.blob)} alt={`Обложка ${item.path}`} />
              )}
              {item.role === "metadata" && metadataText !== null && (
                <pre>{metadataText}</pre>
              )}
              {item.role === "metadata" && metadataText === null && !metadataError && (
                <small role="status">Читаю metadata…</small>
              )}
              {item.role === "metadata" && metadataError && (
                <small role="alert">{metadataError}</small>
              )}
              <code>{item.blob.sha256}</code>
              <small>{item.blob.size.toLocaleString()} bytes · asset {item.asset_id}</small>
            </div>
          ))}
        </article>
      </div>
    </section>
  );
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

function isResolutionDraft(value: unknown): value is ResolutionDraft {
  if (typeof value !== "object" || value === null) return false;
  const draft = value as Partial<ResolutionDraft>;
  return (
    (draft.status === "unresolved" ||
      draft.status === "fixed" ||
      draft.status === "obsolete" ||
      draft.status === "still_wrong") &&
    (draft.currentFindingId === null ||
      typeof draft.currentFindingId === "string")
  );
}

function readDraftSelection(
  value: unknown,
  context: ReviewContext,
): FrameSelection | null {
  if (typeof value !== "object" || value === null) return null;
  const selection = value as Partial<FrameSelection>;
  if (
    !Number.isSafeInteger(selection.startFrame) ||
    !Number.isSafeInteger(selection.endFrameExclusive)
  ) {
    return null;
  }
  const startFrame = selection.startFrame as number;
  const endFrameExclusive = selection.endFrameExclusive as number;
  if (
    startFrame < 0 ||
    endFrameExclusive <= startFrame ||
    clampFrame(startFrame, context) !== startFrame ||
    clampFrame(endFrameExclusive - 1, context) !==
      endFrameExclusive - 1
  ) {
    return null;
  }
  return { startFrame, endFrameExclusive };
}

function readDraftRegion(
  value: unknown,
): ReviewRegion | null | undefined {
  if (value === null) return null;
  if (typeof value !== "object") return undefined;
  const region = value as Partial<ReviewRegion>;
  const coordinates = [
    region.x_milli,
    region.y_milli,
    region.width_milli,
    region.height_milli,
  ];
  if (!coordinates.every(Number.isSafeInteger)) return undefined;
  const [x, y, width, height] = coordinates as number[];
  if (
    x < 0 ||
    y < 0 ||
    width <= 0 ||
    height <= 0 ||
    x + width > 1000 ||
    y + height > 1000
  ) {
    return undefined;
  }
  return {
    x_milli: x,
    y_milli: y,
    width_milli: width,
    height_milli: height,
  };
}

function draftStorageKey(context: ReviewContext): string {
  return [
    "dlstudio.review",
    context.artifact.sha256,
    context.timeline.sha256,
    context.check_report.sha256,
    context.constraints.sha256,
    context.latest_round?.sha256 ?? "first",
    context.latest_round?.size ?? 0,
  ].join(".");
}

function legacyDraftStorageKey(context: ReviewContext): string {
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
  const [previousPack, setPreviousPack] =
    useState<ReviewTaskPack | null>(null);
  const [previousPackState, setPreviousPackState] =
    useState<PreviousPackState>("loading");
  const [activePreviousIndex, setActivePreviousIndex] = useState(0);
  const [showingOld, setShowingOld] = useState(false);
  const [pendingPreviousFindingId, setPendingPreviousFindingId] =
    useState<string | null>(null);
  const [focusComposerToken, setFocusComposerToken] = useState(0);
  const [loadedDraftKey, setLoadedDraftKey] = useState<string | null>(null);
  const [draftStorageWarning, setDraftStorageWarning] =
    useState<string | null>(null);
  const [currentMediaState, setCurrentMediaState] =
    useState<ReviewMediaState>("loading");
  const [comparisonMediaState, setComparisonMediaState] =
    useState<ReviewMediaState>("ready");
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
    const requiredFindings =
      context.latest_verdict?.findings.filter(
        (finding) => finding.requires_change,
      ) ?? [];
    const requiredIds = new Set(
      requiredFindings.map((finding) => finding.finding_id),
    );
    const defaults = Object.fromEntries(
      [...requiredIds].map((findingId) => [
        findingId,
        { status: "unresolved", currentFindingId: null },
      ]),
    ) as Record<string, ResolutionDraft>;
    try {
      const currentRaw = localStorage.getItem(key);
      let value = JSON.parse(currentRaw ?? "null") as {
        findings?: unknown;
        resolutions?: unknown;
        pendingPreviousFindingId?: unknown;
        activePreviousIndex?: unknown;
        note?: unknown;
        selection?: unknown;
        region?: unknown;
      } | null;
      if (currentRaw === null) {
        const legacyRaw = localStorage.getItem(
          legacyDraftStorageKey(context),
        );
        if (legacyRaw !== null) {
          const legacyValue = JSON.parse(legacyRaw) as unknown;
          if (Array.isArray(legacyValue)) {
            value = { findings: legacyValue };
            try {
              localStorage.setItem(key, JSON.stringify(value));
            } catch {
              setDraftStorageWarning(DRAFT_STORAGE_WARNING);
            }
          }
        }
      }
      const storedFindings = Array.isArray(value?.findings)
        ? value.findings.filter(isDraftFinding)
        : [];
      const storedResolutions =
        typeof value?.resolutions === "object" &&
        value.resolutions !== null
          ? Object.fromEntries(
              Object.entries(value.resolutions).filter(
                ([findingId, draft]) =>
                  requiredIds.has(findingId) && isResolutionDraft(draft),
              ),
            )
          : {};
      const nextResolutions = {
        ...defaults,
        ...storedResolutions,
      };
      const storedSelection = readDraftSelection(
        value?.selection,
        context,
      );
      const storedRegion = readDraftRegion(value?.region);
      const storedNote =
        typeof value?.note === "string" ? value.note : "";
      const storedActiveIndex =
        Number.isSafeInteger(value?.activePreviousIndex) &&
        Number(value?.activePreviousIndex) >= 0
          ? Math.min(
              Number(value?.activePreviousIndex),
              Math.max(0, requiredFindings.length - 1),
            )
          : 0;
      const pendingId =
        typeof value?.pendingPreviousFindingId === "string" &&
        requiredIds.has(value.pendingPreviousFindingId)
          ? value.pendingPreviousFindingId
          : null;
      const pendingDraft =
        pendingId === null ? null : nextResolutions[pendingId];
      const canRestorePending =
        pendingId !== null &&
        pendingDraft?.status === "still_wrong" &&
        pendingDraft.currentFindingId === null &&
        storedNote.trim().length > 0 &&
        storedSelection !== null &&
        storedRegion !== undefined;
      for (const [findingId, draft] of Object.entries(
        nextResolutions,
      )) {
        if (
          draft.status === "still_wrong" &&
          draft.currentFindingId === null &&
          (!canRestorePending || findingId !== pendingId)
        ) {
          nextResolutions[findingId] = {
            status: "unresolved",
            currentFindingId: null,
          };
        }
      }
      setFindings(storedFindings);
      setResolutionDrafts(nextResolutions);
      setPendingPreviousFindingId(
        canRestorePending ? pendingId : null,
      );
      setActivePreviousIndex(
        canRestorePending && pendingId
          ? requiredFindings.findIndex(
              (finding) => finding.finding_id === pendingId,
            )
          : storedActiveIndex,
      );
      if (
        storedSelection !== null &&
        storedRegion !== undefined
      ) {
        setSelection(storedSelection);
        setRegion(storedRegion);
        setNote(storedNote);
        setCurrentFrame(storedSelection.startFrame);
        requestAnimationFrame(() => {
          const video = videoRef.current;
          if (video) {
            video.pause();
            video.currentTime = frameToSeconds(
              storedSelection.startFrame,
              context,
            );
          }
        });
      } else {
        setSelection({ startFrame: 0, endFrameExclusive: 1 });
        setRegion(null);
        setNote("");
        setCurrentFrame(0);
      }
    } catch {
      removeLocalDraft(key);
      removeLocalDraft(legacyDraftStorageKey(context));
      setFindings([]);
      setResolutionDrafts(defaults);
      setPendingPreviousFindingId(null);
      setActivePreviousIndex(0);
      setSelection({ startFrame: 0, endFrameExclusive: 1 });
      setRegion(null);
      setNote("");
      setCurrentFrame(0);
      setDraftStorageWarning(DRAFT_STORAGE_WARNING);
    }
    setLoadedDraftKey(key);
  }, [context]);

  useEffect(() => {
    if (!context) return;
    const key = draftStorageKey(context);
    if (loadedDraftKey !== key) return;
    try {
      localStorage.setItem(
        key,
        JSON.stringify({
          findings,
          resolutions: resolutionDrafts,
          pendingPreviousFindingId,
          activePreviousIndex,
          note,
          selection,
          region,
        }),
      );
      setDraftStorageWarning(null);
    } catch {
      setDraftStorageWarning(DRAFT_STORAGE_WARNING);
    }
  }, [
    context,
    activePreviousIndex,
    findings,
    loadedDraftKey,
    note,
    pendingPreviousFindingId,
    region,
    resolutionDrafts,
    selection,
  ]);

  useEffect(() => {
    let active = true;
    setPreviousPack(null);
    setShowingOld(false);
    const expectedLatestRound = context?.latest_round;
    if (!expectedLatestRound) {
      setPreviousPackState("ready");
      return () => {
        active = false;
      };
    }
    setPreviousPackState("loading");
    async function loadPreviousPack() {
      const result = await studioV3.GET("/api/v3/review/task-pack");
      if (!active) return;
      if (!result.data) {
        setPreviousPackState("unavailable");
        return;
      }
      if (!sameBlobRef(result.data.latest_round, expectedLatestRound)) {
        setPreviousPackState("mismatch");
        return;
      }
      setPreviousPack(result.data);
      setPreviousPackState("ready");
    }
    void loadPreviousPack().catch(() => {
      if (active) setPreviousPackState("unavailable");
    });
    return () => {
      active = false;
    };
  }, [
    context?.latest_round?.sha256,
    context?.latest_round?.size,
    contextRequest,
  ]);

  useEffect(() => {
    setComparisonMediaState("ready");
  }, [
    previousPack?.artifact.sha256,
    previousPack?.artifact.size,
  ]);

  useEffect(() => {
    if (!showingOld) {
      setComparisonMediaState("ready");
    }
  }, [showingOld]);

  useEffect(() => {
    if (
      !context ||
      !previousPack ||
      previousPackState !== "ready"
    ) {
      return;
    }
    const required = previousPack.verdict.findings.filter(
      (finding) => finding.requires_change,
    );
    const finding =
      required[Math.min(activePreviousIndex, required.length - 1)];
    if (!finding) return;
    if (
      pendingPreviousFindingId === finding.finding_id ||
      note.trim().length > 0
    ) {
      return;
    }
    const currentFindingId =
      resolutionDrafts[finding.finding_id]?.currentFindingId;
    const linked =
      currentFindingId == null
        ? null
        : (findings.find(
            (candidate) =>
              candidate.finding_id === currentFindingId,
          ) ?? null);
    focusPreviousOnCurrent(finding, linked);
  }, [
    activePreviousIndex,
    context?.artifact.sha256,
    context?.artifact.size,
    loadedDraftKey,
    pendingPreviousFindingId,
    previousPack?.latest_round.sha256,
    previousPack?.latest_round.size,
    previousPackState,
  ]);

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

  const contextPreviousFindings =
    context.latest_verdict?.findings.filter(
      (finding) => finding.requires_change,
    ) ?? [];
  const previousFindings =
    previousPackState === "ready" && previousPack
      ? previousPack.verdict.findings.filter(
          (finding) => finding.requires_change,
        )
      : contextPreviousFindings;
  const activePreviousFinding =
    previousFindings.length === 0
      ? null
      : previousFindings[
          Math.min(activePreviousIndex, previousFindings.length - 1)
        ];
  const activePreviousDraft =
    activePreviousFinding === null
      ? null
      : (resolutionDrafts[activePreviousFinding.finding_id] ?? {
          status: "unresolved",
          currentFindingId: null,
        });
  const activeCurrentFinding =
    activePreviousDraft?.currentFindingId === null ||
    activePreviousDraft?.currentFindingId === undefined
      ? null
      : (findings.find(
          (finding) =>
            finding.finding_id === activePreviousDraft.currentFindingId,
        ) ?? null);
  const sameMedia =
    previousPack !== null &&
    sameBlobRef(previousPack.artifact, context.artifact);
  const comparison =
    showingOld &&
    previousPack !== null &&
    activePreviousFinding?.locator
      ? {
          context: previousPack,
          frame: clampFrame(
            activePreviousFinding.locator.start_frame,
            previousPack,
          ),
          selection: {
            startFrame: activePreviousFinding.locator.start_frame,
            endFrameExclusive:
              activePreviousFinding.locator.end_frame_exclusive,
          },
          region: activePreviousFinding.locator.region ?? null,
          sameMedia,
        }
      : null;
  const findingMarkers = findings.flatMap((finding) =>
    finding.locator
      ? [
          {
            id: finding.finding_id,
            frame: finding.locator.start_frame,
          },
        ]
      : [],
  );
  const reviewReady =
    (previousFindings.length === 0 ||
      (previousPackState === "ready" && previousPack !== null)) &&
    currentMediaState === "ready" &&
    (comparison === null ||
      comparison.sameMedia ||
      comparisonMediaState === "ready");
  const mediaError =
    currentMediaState === "error"
      ? "Не удалось открыть текущую точную версию."
      : comparison !== null &&
          !comparison.sameMedia &&
          comparisonMediaState === "error"
        ? "Не удалось открыть точную версию «До»."
        : null;
  const resolutionSummary = previousFindings.reduce<ResolutionSummary>(
    (summary, finding) => {
      const draft = resolutionDrafts[finding.finding_id] ?? {
        status: "unresolved",
        currentFindingId: null,
      };
      if (draft.status === "obsolete") {
        summary.obsolete += 1;
      } else if (draft.status === "still_wrong") {
        summary.stillWrong += 1;
        if (
          draft.currentFindingId === null ||
          !findings.some(
            (current) =>
              current.finding_id === draft.currentFindingId,
          )
        ) {
          summary.pending += 1;
        }
      } else {
        summary.fixed += 1;
      }
      return summary;
    },
    {
      total: previousFindings.length,
      fixed: 0,
      stillWrong: 0,
      obsolete: 0,
      pending: 0,
    },
  );
  const pendingPreviousText =
    pendingPreviousFindingId === null
      ? null
      : (previousFindings.find(
          (finding) =>
            finding.finding_id === pendingPreviousFindingId,
        )?.text ?? null);

  function seekVideo(frame: number): number | undefined {
    if (!context) return undefined;
    const next = clampFrame(frame, context);
    const applySeek = () => {
      const video = videoRef.current;
      if (video) {
        video.pause();
        video.currentTime = frameToSeconds(next, context);
      }
    };
    if (showingOld) {
      setShowingOld(false);
      requestAnimationFrame(applySeek);
    } else {
      applySeek();
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

  function handlePlaybackFrame(frame: number) {
    if (showingOld) return;
    setCurrentFrame(frame);
    setSelection((current) =>
      current.endFrameExclusive === current.startFrame + 1
        ? { startFrame: frame, endFrameExclusive: frame + 1 }
        : current,
    );
  }

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
    const findingId = `studio.ui.${String(sequence).padStart(3, "0")}`;
    const finding: ReviewFindingBody = {
      finding_id: findingId,
      text,
      requires_change: true,
      locator: {
        start_frame: selection.startFrame,
        end_frame_exclusive: selection.endFrameExclusive,
        region,
        target_ids: activeTargets,
      },
    };
    setFindings((current) => [...current, finding]);
    if (pendingPreviousFindingId !== null) {
      resolvePrevious(
        pendingPreviousFindingId,
        "still_wrong",
        findingId,
      );
      setPendingPreviousFindingId(null);
    }
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

  function focusPreviousOnCurrent(
    finding: ReviewFindingBody,
    linkedFinding: ReviewFindingBody | null,
  ) {
    if (linkedFinding?.locator) {
      selectFinding(linkedFinding);
      return;
    }
    if (!previousPack || !context || !finding.locator) return;
    const startFrame = mapFrameByPresentationTime(
      finding.locator.start_frame,
      previousPack,
      context,
    );
    const mappedEnd = mapFrameBoundaryByPresentationTime(
      finding.locator.end_frame_exclusive,
      previousPack,
      context,
    );
    setSelection({
      startFrame,
      endFrameExclusive: Math.max(startFrame + 1, mappedEnd),
    });
    setRegion(null);
    setCurrentFrame(startFrame);
    requestAnimationFrame(() => {
      const video = videoRef.current;
      if (video) {
        video.pause();
        video.currentTime = frameToSeconds(startFrame, context);
      }
    });
  }

  function resolvePrevious(
    findingId: string,
    status: ResolutionStatus,
    currentFindingId: string | null = null,
  ) {
    if (
      findingId === pendingPreviousFindingId &&
      (status !== "still_wrong" || currentFindingId !== null)
    ) {
      setPendingPreviousFindingId(null);
      setNote("");
    }
    setResolutionDrafts((current) => ({
      ...current,
      [findingId]: { status, currentFindingId },
    }));
  }

  function replacePreviousResolution(
    findingId: string,
    status: "unresolved" | "obsolete",
  ) {
    const linkedFindingId =
      resolutionDrafts[findingId]?.currentFindingId;
    if (linkedFindingId) {
      setFindings((current) =>
        current.filter(
          (finding) => finding.finding_id !== linkedFindingId,
        ),
      );
    }
    resolvePrevious(findingId, status);
  }

  function continuePreviousFinding(finding: ReviewFindingBody) {
    if (previousPack === null || context === null || !reviewReady) return;
    if (note.trim()) {
      onError(
        "Сначала сохраните или очистите текущий комментарий, затем продолжите прошлое замечание.",
      );
      return;
    }
    const draft = resolutionDrafts[finding.finding_id];
    const linked =
      draft?.currentFindingId === null ||
      draft?.currentFindingId === undefined
        ? null
        : findings.find(
            (current) =>
              current.finding_id === draft.currentFindingId,
          );
    if (linked) {
      selectFinding(linked);
      return;
    }
    setShowingOld(false);
    setPendingPreviousFindingId(finding.finding_id);
    resolvePrevious(finding.finding_id, "still_wrong", null);
    focusPreviousOnCurrent(finding, null);
    setNote(finding.text);
    setFocusComposerToken((current) => current + 1);
    onError(null);
  }

  function removeFinding(findingId: string) {
    const removed = findings.find(
      (finding) => finding.finding_id === findingId,
    );
    const linkedPrevious = Object.entries(resolutionDrafts).find(
      ([, draft]) => draft.currentFindingId === findingId,
    )?.[0];
    setFindings((current) =>
      current.filter((finding) => finding.finding_id !== findingId),
    );
    if (linkedPrevious) {
      const linkedPreviousIndex = previousFindings.findIndex(
        (finding) => finding.finding_id === linkedPrevious,
      );
      if (linkedPreviousIndex >= 0) {
        setActivePreviousIndex(linkedPreviousIndex);
      }
      setPendingPreviousFindingId(linkedPrevious);
      resolvePrevious(linkedPrevious, "still_wrong", null);
      const previous = previousFindings.find(
        (finding) => finding.finding_id === linkedPrevious,
      );
      setNote(previous?.text ?? "");
      if (removed?.locator) {
        setSelection({
          startFrame: removed.locator.start_frame,
          endFrameExclusive: removed.locator.end_frame_exclusive,
        });
        setRegion(removed.locator.region ?? null);
        seekVideo(removed.locator.start_frame);
      }
      setFocusComposerToken((current) => current + 1);
    }
  }

  function retryMedia() {
    if (currentMediaState === "error") {
      setCurrentMediaState("loading");
      videoRef.current?.load();
      return;
    }
    if (comparisonMediaState === "error") {
      setComparisonMediaState("loading");
      setShowingOld(false);
      requestAnimationFrame(() => setShowingOld(true));
    }
  }

  async function submit(outcome: "pass" | "changes_requested") {
    if (!context) return;
    if (!reviewReady) {
      onError("Сначала загрузите точную прошлую версию.");
      return;
    }
    if (
      context.latest_round !== null &&
      context.latest_verdict === null
    ) {
      onError("Предыдущий review повреждён или ещё не загружен.");
      return;
    }
    const draftKey = draftStorageKey(context);
    const resolutions = [];
    const linkedCurrentFindings = new Set<string>();
    for (const previous of previousFindings) {
      const draft = resolutionDrafts[previous.finding_id];
      let status = draft?.status ?? "unresolved";
      if (outcome === "pass" && status === "still_wrong") {
        onError(
          "Нельзя одобрить версию, пока замечание отмечено «всё ещё не так».",
        );
        return;
      }
      if (status === "unresolved") {
        status = "fixed";
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
      if (
        currentFindingId &&
        linkedCurrentFindings.has(currentFindingId)
      ) {
        onError(
          "Один новый комментарий нельзя связать с двумя прошлыми замечаниями.",
        );
        return;
      }
      if (currentFindingId) {
        linkedCurrentFindings.add(currentFindingId);
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
          expected_artifact_report: context.artifact_report,
          expected_publication_manifest: context.publication_manifest,
          expected_check_report: context.check_report,
          expected_constraints: context.constraints,
          expected_latest_round: context.latest_round,
          resolutions,
          outcome,
          scope: ["visual", "audio", "constraints", "publication"],
          reviewer: "author",
          reviewed_at: new Date().toISOString(),
          findings: outcome === "pass" ? [] : findings,
        },
      });
      if (result.error || !result.data) {
        if (result.response.status === 409) {
          const statusResult = await studioV3.GET("/api/v3/status");
          if (statusResult.data) {
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
      removeLocalDraft(draftKey);
      removeLocalDraft(legacyDraftStorageKey(context));
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
          <h2 id="review-title">
            {previousFindings.length > 0
              ? "Проверьте исправления"
              : "Посмотрите и отметьте, что изменить"}
          </h2>
          <p class="review-intro">
            {previousFindings.length > 0
              ? "Сравните исправления. Если что-то всё ещё не так — отметьте это."
              : "Кликните по кадру или протяните диапазон на шкале. Рамкой на видео можно показать точную область."}
          </p>
        </div>
      </div>
      {draftStorageWarning && (
        <p class="draft-storage-warning" role="status">
          {draftStorageWarning}
        </p>
      )}

      <ReviewEvidence context={context} />

      <div class="review-grid">
        <div class="review-visuals">
          {activePreviousFinding && activePreviousDraft && (
            <PreviousFindingsReview
              pack={previousPack}
              packState={previousPackState}
              finding={activePreviousFinding}
              index={Math.min(
                activePreviousIndex,
                previousFindings.length - 1,
              )}
              total={previousFindings.length}
              draft={activePreviousDraft}
              currentFinding={activeCurrentFinding}
              pendingCapture={
                pendingPreviousFindingId ===
                activePreviousFinding.finding_id
              }
              showingOld={showingOld}
              sameMedia={sameMedia}
              submitting={submitting}
              reviewReady={reviewReady}
              navigationLocked={
                pendingPreviousFindingId !== null ||
                note.trim().length > 0
              }
              onPrevious={() => {
                setShowingOld(false);
                setActivePreviousIndex((current) =>
                  (current - 1 + previousFindings.length) %
                  previousFindings.length,
                );
              }}
              onNext={() => {
                setShowingOld(false);
                setActivePreviousIndex(
                  (current) => (current + 1) % previousFindings.length,
                );
              }}
              onShowOld={setShowingOld}
              onStillWrong={() =>
                continuePreviousFinding(activePreviousFinding)
              }
              onObsolete={() => {
                setShowingOld(false);
                replacePreviousResolution(
                  activePreviousFinding.finding_id,
                  activePreviousDraft.status === "obsolete"
                    ? "unresolved"
                    : "obsolete",
                );
              }}
              onDefaultFixed={() =>
                replacePreviousResolution(
                  activePreviousFinding.finding_id,
                  "unresolved",
                )
              }
              onOpenCurrentFinding={() => {
                if (activeCurrentFinding) {
                  selectFinding(activeCurrentFinding);
                }
              }}
              onRetry={() =>
                setContextRequest((current) => current + 1)
              }
            />
          )}
          <ReviewPlayer
            context={context}
            currentFrame={currentFrame}
            videoRef={videoRef as RefObject<HTMLVideoElement>}
            region={region}
            comparison={comparison}
            comparisonLabel={
              showingOld
                ? "ДО · прошлая версия · без разметки"
                : previousFindings.length > 0
                  ? "СЕЙЧАС · новая версия"
                  : null
            }
            onCurrentMediaState={setCurrentMediaState}
            onComparisonMediaState={setComparisonMediaState}
            onFrame={handlePlaybackFrame}
            onRegion={setRegion}
            onSeek={seek}
          />
          {mediaError && (
            <div class="media-error" role="alert">
              <span>
                {mediaError} Подтверждение заблокировано, пока видео
                недоступно.
              </span>
              <button type="button" class="quiet" onClick={retryMedia}>
                Повторить
              </button>
            </div>
          )}
          <div hidden={showingOld}>
            <FrameStrip
              context={context}
              currentFrame={currentFrame}
              selection={selection}
              markers={findingMarkers}
              onSelect={selectTime}
            />
          </div>
        </div>
        <ReviewNotes
          context={context}
          selection={selection}
          region={region}
          activeTargets={activeTargets}
          findings={findings}
          resolutionSummary={resolutionSummary}
          pendingPreviousText={pendingPreviousText}
          focusComposerToken={focusComposerToken}
          note={note}
          submitting={submitting}
          readOnly={showingOld}
          reviewReady={reviewReady}
          onNote={setNote}
          onAdd={addFinding}
          onRemove={removeFinding}
          onSelect={selectFinding}
          onSubmit={(outcome) => void submit(outcome)}
        />
      </div>

      <details class="technical-details" hidden={showingOld}>
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
