import { useState } from "preact/hooks";
import type { components } from "./api/v3.gen";

type Status = components["schemas"]["WorkflowStatus"];
type Workflow = components["schemas"]["WorkflowRun"];
type CurrentReview = components["schemas"]["ReviewVerdict"];
type BlobRef = components["schemas"]["BlobRef"];
type DeliveryContext = components["schemas"]["DeliveryContext"];

type WorkflowDashboardProps = {
  status: Status;
  workflow: Workflow;
  busy: boolean;
  currentReview: CurrentReview | null;
  deliveryContext: DeliveryContext | null;
  onAdvance: () => void;
  onDeliver: (destinationId: string, expectedCandidate: BlobRef) => void;
};

function shortHash(ref: BlobRef | null | undefined): string {
  return ref
    ? `${ref.sha256.slice(0, 12)} · ${ref.size.toLocaleString()} bytes`
    : "—";
}

function failureGuidance(error: string): { owner: string; action: string } | null {
  if (error.includes("audio.voice.required")) {
    return { owner: "Авторский монтаж", action: "Добавьте AudioClip с выбранным дублем." };
  }
  if (error.includes("audio.voice.silent")) {
    return {
      owner: "Финальный звук",
      action: "Финальный звук не содержит слышимого сигнала. Запишите или выберите другой дубль.",
    };
  }
  if (error.includes("package.cover.required") || error.includes("requires cover")) {
    return { owner: "Publication package", action: "Добавьте обязательную обложку." };
  }
  if (error.includes("package.metadata.required") || error.includes("requires metadata")) {
    return { owner: "Publication package", action: "Добавьте обязательные metadata." };
  }
  return null;
}

export function WorkflowDashboard({
  status,
  workflow,
  busy,
  currentReview,
  deliveryContext,
  onAdvance,
  onDeliver,
}: WorkflowDashboardProps) {
  const [destination, setDestination] = useState("local.delivery");
  const stage = status.current_stage;
  const failed = workflow.attempts.find((item) => item.state === "failed");
  const guidance = failed?.error ? failureGuidance(failed.error) : null;
  const waitingForRevision =
    (stage === "review" || stage === "package") &&
    currentReview !== null &&
    currentReview.outcome !== "pass";

  return (
    <>
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

      <section class="workflow" aria-labelledby="workflow-title">
        <div class="section-head">
          <div>
            <p class="label">Canonical progress</p>
            <h2 id="workflow-title">Release workflow</h2>
          </div>
          {busy && (
            <span class="working" role="status">
              Работаю…
            </span>
          )}
        </div>
        <ol class="stages">
          {status.stage_order.map((item, index) => {
            const attempt = workflow.attempts.find(
              (entry) => entry.stage === item,
            );
            const state =
              attempt?.state ?? (stage === item ? "current" : "pending");
            return (
              <li
                key={item}
                class={`stage ${state}`}
                aria-current={stage === item ? "step" : undefined}
              >
                <span class="stage-index">
                  {String(index + 1).padStart(2, "0")}
                </span>
                <span>{item}</span>
                <small>{state}</small>
              </li>
            );
          })}
        </ol>
        {failed?.error && (
          <div class="failure" role="alert">
            <p>Последняя ошибка: {failed.error}</p>
            {guidance && (
              <p><strong>{guidance.owner}:</strong> {guidance.action}</p>
            )}
          </div>
        )}
      </section>

      <section class="action" aria-labelledby="action-title">
        <p class="label">Следующее полезное действие</p>
        <h2 id="action-title">
          {waitingForRevision
            ? "Замечания переданы"
            : stage
              ? `Продолжить ${stage}`
              : "Release complete"}
        </h2>

        {stage === "package" && currentReview === null && (
          <p class="muted">Проверяю зафиксированный verdict…</p>
        )}
        {waitingForRevision && currentReview && (
          <div class="waiting-revision">
            <p>
              Эта версия не пойдёт в package. Я могу прочитать exact verdict
              через API, изменить authoring и собрать новую.
            </p>
            <ol>
              {currentReview.findings.map((finding) => (
                <li key={finding.finding_id}>{finding.text}</li>
              ))}
            </ol>
          </div>
        )}
        {status.action === "advance" &&
          stage !== "package" &&
          !waitingForRevision && (
            <button class="primary" disabled={busy} onClick={onAdvance}>
              Advance workflow
            </button>
          )}
        {status.action === "advance" &&
          stage === "package" &&
          currentReview?.outcome === "pass" && (
            <button class="primary" disabled={busy} onClick={onAdvance}>
              Собрать release
            </button>
          )}
        {status.action === "deliver" && (
          <div class="delivery-confirmation">
            <h3>Frozen package</h3>
            {deliveryContext === null ? (
              <p class="muted" role="status">Читаю exact release candidate…</p>
            ) : (
              <ul class="delivery-files">
                {deliveryContext.files.map((item) => (
                  <li key={item.path}>
                    <strong>{item.path}</strong>
                    <span>{item.blob.size.toLocaleString()} bytes</span>
                    <code>{item.blob.sha256}</code>
                  </li>
                ))}
              </ul>
            )}
            <form
              class="delivery"
              onSubmit={(event) => {
                event.preventDefault();
                if (deliveryContext) {
                  onDeliver(destination, deliveryContext.candidate);
                }
              }}
            >
              <label>
                Destination ID
                <input
                  value={destination}
                  onInput={(event) =>
                    setDestination(event.currentTarget.value)
                  }
                  required
                />
              </label>
              <button class="primary" disabled={busy || deliveryContext === null}>
                Deliver frozen candidate
              </button>
            </form>
          </div>
        )}
        {status.completed && (
          <p class="complete">
            Receipt{" "}
            {workflow.delivery_receipt
              ? workflow.delivery_receipt.sha256.slice(0, 12)
              : "—"}
          </p>
        )}
      </section>
    </>
  );
}
