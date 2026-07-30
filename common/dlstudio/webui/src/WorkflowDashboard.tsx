import { useState } from "preact/hooks";
import type { components } from "./api/v3.gen";

type Status = components["schemas"]["WorkflowStatus"];
type Workflow = components["schemas"]["WorkflowRun"];
type CurrentReview = components["schemas"]["ReviewVerdict"];
type BlobRef = components["schemas"]["BlobRef"];

type WorkflowDashboardProps = {
  status: Status;
  workflow: Workflow;
  busy: boolean;
  currentReview: CurrentReview | null;
  onAdvance: () => void;
  onDeliver: (destinationId: string) => void;
};

function shortHash(ref: BlobRef | null | undefined): string {
  return ref
    ? `${ref.sha256.slice(0, 12)} · ${ref.size.toLocaleString()} bytes`
    : "—";
}

export function WorkflowDashboard({
  status,
  workflow,
  busy,
  currentReview,
  onAdvance,
  onDeliver,
}: WorkflowDashboardProps) {
  const [destination, setDestination] = useState("local.delivery");
  const stage = status.current_stage;
  const failed = workflow.attempts.find((item) => item.state === "failed");
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
          <p class="failure">Последняя ошибка: {failed.error}</p>
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
          <form
            class="delivery"
            onSubmit={(event) => {
              event.preventDefault();
              onDeliver(destination);
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
            <button class="primary" disabled={busy}>
              Deliver frozen candidate
            </button>
          </form>
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
