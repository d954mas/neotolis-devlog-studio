import type {
  AutopilotCheckpointData,
  AutopilotRequestAction,
} from "../api/types";

interface Props {
  checkpoint: AutopilotCheckpointData | null;
  busy: boolean;
  error: string | null;
  onApproveAll: () => Promise<void>;
  onRequest: (
    action: AutopilotRequestAction,
    shotId: string,
  ) => Promise<void>;
}

const ACTIONS: Array<[AutopilotRequestAction, string]> = [
  ["replace_shot", "Replace shot"],
  ["request_capture", "Request capture"],
  ["change_text", "Change text"],
];

export function AutopilotCheckpoint({
  checkpoint,
  busy,
  error,
  onApproveAll,
  onRequest,
}: Props) {
  if (!checkpoint) {
    return (
      <div class="autopilot-checkpoint center-msg">
        {error ? <span class="err-text">{error}</span> : "Loading checkpoint…"}
      </div>
    );
  }
  const wall = checkpoint.wall_time;
  const overBudget = wall.elapsed_minutes > wall.budget_minutes;
  return (
    <div class="autopilot-checkpoint">
      <div class="checkpoint-head">
        <div>
          <div class="eyebrow">Single author checkpoint</div>
          <h2>Autopilot decisions</h2>
        </div>
        <div class={"wall-budget" + (overBudget ? " over" : "")}>
          <b>{wall.elapsed_minutes.toFixed(1)} / {wall.budget_minutes.toFixed(1)} min</b>
          <span>{wall.stage} · {wall.remaining_minutes.toFixed(1)} min left</span>
        </div>
        <button
          class="btn"
          disabled={busy || !checkpoint.can_approve_all || checkpoint.approved_all}
          onClick={onApproveAll}
        >
          {checkpoint.approved_all ? "Approved" : "Approve all"}
        </button>
      </div>

      {error && <div class="checkpoint-error">{error}</div>}
      <div class={"checkpoint-blockers" + (checkpoint.blockers.length ? " blocked" : " clear")}>
        <b>{checkpoint.blockers.length ? `${checkpoint.blockers.length} blocker(s)` : "No blockers"}</b>
        {checkpoint.blockers.map((issue) => (
          <span key={`${issue.code}:${issue.where || issue.message}`}>
            <code>{issue.code}</code> {issue.message}
            {issue.where ? <small>{issue.where}</small> : null}
          </span>
        ))}
      </div>
      {!!checkpoint.notices?.length && (
        <div class="checkpoint-blockers notices">
          <b>{checkpoint.notices.length} quality notice(s)</b>
          {checkpoint.notices.map((issue) => (
            <span key={`${issue.code}:${issue.where || issue.message}`}>
              <code>{issue.code}</code> {issue.message}
              {issue.where ? <small>{issue.where}</small> : null}
            </span>
          ))}
        </div>
      )}

      <div class="checkpoint-table-wrap">
        <table class="checkpoint-table">
          <thead>
            <tr>
              <th>VO thesis</th>
              <th>Shot / provenance</th>
              <th>Duration / quality / proposed fix</th>
              <th>Decision</th>
            </tr>
          </thead>
          <tbody>
            {checkpoint.rows.map((row) => (
              <tr key={row.id} class={row.approved ? "approved" : ""}>
                <td>
                  <span class="shot-id">{row.id}</span>
                  <p>{row.vo_thesis || <em>No VO thesis</em>}</p>
                </td>
                <td>
                  <code class="shot-src">{row.shot.src || "No source"}</code>
                  <div class="provenance">
                    {row.shot.provenance} · {row.shot.source_role}
                  </div>
                </td>
                <td>
                  <b>{row.duration_seconds.toFixed(2)}s</b>
                  <div class="quality-flags">
                    {row.quality_flags.length
                      ? row.quality_flags.map((flag) => <span key={flag}>{flag}</span>)
                      : <span class="ok">clean</span>}
                  </div>
                  <p class="proposed-fix">{row.proposed_fix || "No fix proposed"}</p>
                </td>
                <td>
                  <div class="checkpoint-actions">
                    {ACTIONS.map(([action, label]) => (
                      <button
                        key={action}
                        class="btn secondary sm"
                        disabled={busy}
                        onClick={() => onRequest(action, row.id)}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                  {row.approved && <span class="approved-mark">Approved</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!checkpoint.rows.length && (
          <div class="empty">No shot rows. Generate the shot manifest and preflight first.</div>
        )}
      </div>
    </div>
  );
}
