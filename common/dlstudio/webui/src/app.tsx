import { useEffect, useRef, useState } from "preact/hooks";
import { studioV3 } from "./api/v3.client";
import type { components } from "./api/v3.gen";
import { ReviewWorkspace } from "./review/ReviewWorkspace";
import { WorkflowDashboard } from "./WorkflowDashboard";

type Status = components["schemas"]["WorkflowStatus"];
type BlobRef = components["schemas"]["BlobRef"];
type CurrentReview = components["schemas"]["ReviewVerdict"];

function readStatus(data: Status | undefined, error: unknown): Status {
  if (error) throw new Error(JSON.stringify(error));
  if (!data) throw new Error("API не вернул состояние производства.");
  return data;
}

function shortHash(ref: BlobRef | null | undefined): string {
  return ref
    ? `${ref.sha256.slice(0, 12)} · ${ref.size.toLocaleString()} bytes`
    : "—";
}

export function App() {
  const contentRef = useRef<HTMLElement>(null);
  const wasReviewing = useRef(false);
  const [status, setStatus] = useState<Status | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [currentReview, setCurrentReview] =
    useState<CurrentReview | null>(null);
  const [reviewRequestVersion, setReviewRequestVersion] = useState(0);

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
  const reviewing = status?.action === "review" && workflow !== undefined;

  useEffect(() => {
    if (wasReviewing.current && !reviewing) {
      requestAnimationFrame(() => contentRef.current?.focus());
    }
    wasReviewing.current = reviewing;
  }, [reviewing]);

  useEffect(() => {
    if (stage !== "package") {
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
          setError("Нет текущего verdict.");
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

  return (
    <div class={`shell ${reviewing ? "review-shell" : ""}`}>
      <header class={`topbar ${reviewing ? "review-topbar" : ""}`}>
        <div>
          <p class="eyebrow">
            {reviewing ? "Ревью версии" : "DLSTUDIO / ЛОКАЛЬНОЕ ПРОИЗВОДСТВО"}
          </p>
          <h1>{reviewing ? workflow?.production_id : "Studio v3"}</h1>
        </div>
        <button class="quiet" onClick={refresh} disabled={busy}>
          Обновить
        </button>
      </header>

      {error && (
        <div class="alert" role="alert">
          {error}
        </div>
      )}
      {!status || !workflow ? (
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
          {!reviewing && (
            <section class="summary" aria-labelledby="production-title">
            <div>
              <p class="label">Production</p>
              <h2 id="production-title">{workflow.production_id}</h2>
              <p class="muted">
                {workflow.kind} · run {workflow.run_id} · revision{" "}
                {workflow.revision}
              </p>
            </div>
            <div class="fact">
              <span>Текущий этап</span>
              <strong>{stage ?? "готово"}</strong>
            </div>
            <div class="fact">
              <span>Eligible candidate</span>
              <strong class="hash">
                {shortHash(workflow.eligible_candidate)}
              </strong>
            </div>
            </section>
          )}

          {status.action === "review" ? (
            <ReviewWorkspace
              key={`${workflow.run_id}:${workflow.revision}`}
              onError={setError}
              onSubmitted={(next) => {
                setCurrentReview(null);
                setStatus(next);
              }}
            />
          ) : (
            <WorkflowDashboard
              status={status}
              workflow={workflow}
              busy={busy}
              currentReview={currentReview}
              onAdvance={() =>
                void perform(async () => {
                  const result = await studioV3.POST("/api/v3/advance");
                  return readStatus(result.data, result.error);
                })
              }
              onDeliver={(destinationId) =>
                void perform(async () => {
                  const result = await studioV3.POST("/api/v3/deliver", {
                    body: { destination_id: destinationId },
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
