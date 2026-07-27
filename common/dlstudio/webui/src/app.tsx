import { useEffect, useState } from "preact/hooks";
import { studioV3 } from "./api/v3.client";
import type { components } from "./api/v3.gen";

type Status = components["schemas"]["WorkflowStatus"];
type BlobRef = components["schemas"]["BlobRef"];
type Outcome = components["schemas"]["ReviewVerdictBody"]["outcome"];

function readStatus(data: Status | undefined, error: unknown): Status {
  if (error) throw new Error(JSON.stringify(error));
  if (!data) throw new Error("The API returned no workflow projection.");
  return data;
}

function shortHash(ref: BlobRef | null | undefined): string {
  return ref ? `${ref.sha256.slice(0, 12)} · ${ref.size.toLocaleString()} bytes` : "—";
}

export function App() {
  const [status, setStatus] = useState<Status | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<Outcome>("pass");
  const [reviewer, setReviewer] = useState("author");
  const [scope, setScope] = useState("visual,audio,constraints");
  const [finding, setFinding] = useState("");
  const [destination, setDestination] = useState("local.delivery");

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
      return readStatus(result.data, result.error);
    });
  }

  useEffect(() => {
    void refresh();
  }, []);

  const workflow = status?.workflow;
  const stage = status?.current_stage;
  const failed = workflow?.attempts.find((item) => item.state === "failed");
  const reviewReady =
    outcome !== "changes_requested" || finding.trim().length > 0;

  return (
    <div class="shell">
      <header class="topbar">
        <div>
          <p class="eyebrow">DLSTUDIO / LOCAL PRODUCTION</p>
          <h1>Studio v3</h1>
        </div>
        <button class="quiet" onClick={refresh} disabled={busy}>
          Refresh
        </button>
      </header>

      {error && <div class="alert" role="alert">{error}</div>}
      {!status || !workflow ? (
        <main class="loading" aria-busy={busy}>
          <p>{busy ? "Loading canonical workflow…" : "No active workflow."}</p>
          {!busy && <button class="primary" onClick={() => perform(async () => {
            const result = await studioV3.POST("/api/v3/advance");
            return readStatus(result.data, result.error);
          })}>Start production</button>}
        </main>
      ) : (
        <main>
          <section class="summary" aria-labelledby="production-title">
            <div>
              <p class="label">Production</p>
              <h2 id="production-title">{workflow.production_id}</h2>
              <p class="muted">{workflow.kind} · run {workflow.run_id} · revision {workflow.revision}</p>
            </div>
            <div class="fact">
              <span>Current stage</span>
              <strong>{stage ?? "complete"}</strong>
            </div>
            <div class="fact">
              <span>Eligible candidate</span>
              <strong class="hash">{shortHash(workflow.eligible_candidate)}</strong>
            </div>
          </section>

          <section class="workflow" aria-labelledby="workflow-title">
            <div class="section-head">
              <div>
                <p class="label">Canonical progress</p>
                <h2 id="workflow-title">Release workflow</h2>
              </div>
              {busy && <span class="working" role="status">Working…</span>}
            </div>
            <ol class="stages">
              {status.stage_order.map((item, index) => {
                const attempt = workflow.attempts.find((entry) => entry.stage === item);
                const state = attempt?.state ?? (stage === item ? "current" : "pending");
                return (
                  <li key={item} class={`stage ${state}`} aria-current={stage === item ? "step" : undefined}>
                    <span class="stage-index">{String(index + 1).padStart(2, "0")}</span>
                    <span>{item}</span>
                    <small>{state}</small>
                  </li>
                );
              })}
            </ol>
            {failed?.error && <p class="failure">Last failure: {failed.error}</p>}
          </section>

          <section class="action" aria-labelledby="action-title">
            <p class="label">Next action</p>
            <h2 id="action-title">{stage ? `Continue ${stage}` : "Release complete"}</h2>

            {status.action === "advance" && (
              <button class="primary" disabled={busy} onClick={() => perform(async () => {
                const result = await studioV3.POST("/api/v3/advance");
                return readStatus(result.data, result.error);
              })}>Advance workflow</button>
            )}

            {status.action === "review" && (
              <form onSubmit={(event) => {
                event.preventDefault();
                void perform(async () => {
                  const result = await studioV3.POST("/api/v3/review", { body: {
                    outcome,
                    scope: scope.split(",").map((item) => item.trim()).filter(Boolean),
                    reviewer,
                    reviewed_at: new Date().toISOString(),
                    findings: finding.trim() ? [{
                      finding_id: "studio.ui.review",
                      text: finding.trim(),
                      requires_change: outcome === "changes_requested",
                    }] : [],
                  } });
                  return readStatus(result.data, result.error);
                });
              }}>
                <label>Verdict<select value={outcome} onChange={(e) => setOutcome(e.currentTarget.value as Outcome)}>
                  <option value="pass">Pass</option><option value="changes_requested">Changes requested</option><option value="block">Block</option>
                </select></label>
                <label>Reviewer<input value={reviewer} onInput={(e) => setReviewer(e.currentTarget.value)} required /></label>
                <label>Scope<input value={scope} onInput={(e) => setScope(e.currentTarget.value)} required /></label>
                <label class="wide">Finding<textarea value={finding} onInput={(e) => setFinding(e.currentTarget.value)} placeholder="Evidence-based note" /></label>
                <button class="primary" disabled={busy || !reviewReady}>Submit exact review</button>
              </form>
            )}

            {status.action === "deliver" && (
              <form class="delivery" onSubmit={(event) => {
                event.preventDefault();
                void perform(async () => {
                  const result = await studioV3.POST("/api/v3/deliver", { body: { destination_id: destination } });
                  return readStatus(result.data?.status, result.error);
                });
              }}>
                <label>Destination ID<input value={destination} onInput={(e) => setDestination(e.currentTarget.value)} required /></label>
                <button class="primary" disabled={busy}>Deliver frozen candidate</button>
              </form>
            )}

            {status.completed && <p class="complete">Receipt {shortHash(workflow.delivery_receipt)}</p>}
          </section>
        </main>
      )}
    </div>
  );
}
