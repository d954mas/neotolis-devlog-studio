import { useEffect, useRef, useState } from "preact/hooks";
import { studioV3 } from "./api/v3.client";
import type { components } from "./api/v3.gen";
import { ReviewWorkspace } from "./review/ReviewWorkspace";
import { sameBlobRef } from "./review/types";
import { StudioHeader } from "./StudioHeader";
import { VoiceRecorder } from "./voice/VoiceRecorder";
import { WorkflowDashboard } from "./WorkflowDashboard";
import { useDeliveryContext } from "./delivery/useDeliveryContext";
type Status = components["schemas"]["WorkflowStatus"];
type CurrentReview = components["schemas"]["ReviewVerdict"];
function readStatus(data: Status | undefined, error: unknown): Status {
  if (error) throw new Error(JSON.stringify(error));
  if (!data) throw new Error("API не вернул состояние производства.");
  return data;
}
export function App() {
  const contentRef = useRef<HTMLElement>(null);
  const wasReviewing = useRef(false);
  const [status, setStatus] = useState<Status | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [currentReview, setCurrentReview] = useState<CurrentReview | null>(null);
  const [reviewRequestVersion, setReviewRequestVersion] = useState(0);
  const [mode, setMode] = useState<"production" | "voice">(
    window.location.hash === "#voice" ? "voice" : "production",
  );
  async function perform(request: () => Promise<Status>) {
    setBusy(true);
    setError(null);
    try {
      setStatus(await request());
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }
  function refresh() {
    return perform(async () => {
      const result = await studioV3.GET("/api/v3/status");
      const next = readStatus(result.data, result.error);
      setReviewRequestVersion((current) => current + 1);
      return next;
    });
  }
  useEffect(() => {
    void refresh();
  }, []);
  const workflow = status?.workflow;
  const stage = status?.current_stage;
  const prepared = workflow?.attempts.find(
    (attempt) =>
      attempt.stage === "prepare" && attempt.state === "succeeded",
  );
  const finalized = workflow?.attempts.find(
    (attempt) =>
      attempt.stage === "final" && attempt.state === "succeeded",
  );
  const finalArtifact = finalized
    ?.outputs.find((output) => output.name === "artifact")?.blob;
  const currentCheckReport = prepared?.outputs.find(
    (output) => output.name === "check_report",
  )?.blob;
  const currentConstraints = prepared?.outputs.find(
    (output) => output.name === "constraints",
  )?.blob;
  const waitingForRevision =
    stage === "review" &&
    currentReview !== null &&
    currentReview.outcome !== "pass" &&
    sameBlobRef(currentReview.artifact, finalArtifact) &&
    sameBlobRef(currentReview.check_report, currentCheckReport) &&
    sameBlobRef(currentReview.constraints, currentConstraints);
  const reviewing =
    status?.action === "review" &&
    workflow !== undefined &&
    !waitingForRevision;
  const deliveryContext = useDeliveryContext(status?.action === "deliver", workflow?.revision, setError);

  useEffect(() => {
    if (wasReviewing.current && !reviewing) {
      requestAnimationFrame(() => contentRef.current?.focus());
    }
    wasReviewing.current = reviewing;
  }, [reviewing]);

  useEffect(() => {
    if (!(stage === "review" || stage === "package")) {
      setCurrentReview(null);
      return;
    }
    setCurrentReview(null);
    let active = true;
    void studioV3
      .GET("/api/v3/review/current")
      .then((result) => {
        if (!active) return;
        if (!result.data) {
          if (stage === "package") setError("Нет текущего verdict.");
        } else {
          setCurrentReview(result.data);
        }
      })
      .catch((cause: unknown) => {
        if (active) {
          setError(cause instanceof Error ? cause.message : String(cause));
        }
      });
    return () => {
      active = false;
    };
  }, [reviewRequestVersion, stage, workflow?.revision]);

  function changeMode(next: "production" | "voice") {
    setMode(next);
    window.location.hash = next === "voice" ? "voice" : "";
  }
  return (
    <div class={`shell ${reviewing && mode === "production" ? "review-shell" : ""}`}>
      <StudioHeader
        mode={mode}
        reviewing={reviewing && mode === "production"}
        productionId={workflow?.production_id}
        busy={busy}
        onMode={changeMode}
        onRefresh={() => mode === "voice" ? window.location.reload() : void refresh()}
      />

      {error && (
        <div class="alert" role="alert">
          {error}
        </div>
      )}
      {mode === "voice" ? (
        <main class="voice-main" ref={contentRef} tabIndex={-1}>
          <VoiceRecorder />
        </main>
      ) : !status || !workflow ? (
        <main ref={contentRef} class="loading" aria-busy={busy} tabIndex={-1}>
          <p>
            {busy
              ? "Читаю каноническое состояние…"
              : "Активного производства пока нет."}
          </p>
          {!busy && (
            <button
              class="primary"
              onClick={() =>
                perform(async () => {
                  const result = await studioV3.POST("/api/v3/advance");
                  return readStatus(result.data, result.error);
                })
              }
            >
              Start production
            </button>
          )}
        </main>
      ) : (
        <main ref={contentRef} class={reviewing ? "review-main" : ""} tabIndex={-1}>
          {reviewing ? (
            <ReviewWorkspace
              key={`${workflow.run_id}:${workflow.revision}`}
              onError={setError}
              onSubmitted={(next) => {
                setCurrentReview(null);
                setStatus(next);
                setReviewRequestVersion((current) => current + 1);
              }}
            />
          ) : (
            <WorkflowDashboard
              status={status}
              workflow={workflow}
              busy={busy}
              currentReview={currentReview}
              deliveryContext={deliveryContext}
              onAdvance={() =>
                void perform(async () => {
                  const result = await studioV3.POST("/api/v3/advance");
                  return readStatus(result.data, result.error);
                })
              }
              onDeliver={(destinationId, expectedCandidate) =>
                void perform(async () => {
                  const result = await studioV3.POST("/api/v3/deliver", {
                    body: { destination_id: destinationId, expected_candidate: expectedCandidate },
                  });
                  return readStatus(result.data?.status, result.error);
                })
              }
            />
          )}
        </main>
      )}
    </div>
  );
}
