import type { CheckReport, Project, ProjectBeat } from "../api/types";
import { fmtDuration } from "../lib/format";

interface Props {
  project: Project;
  activeBeatId: string | null;
  check: CheckReport | null;
  onSelect: (beatId: string) => void;
}

type BeatSeverity = "error" | "warn" | null;

function beatSeverity(check: CheckReport | null, beatId: string): BeatSeverity {
  if (!check) return null;
  let sev: BeatSeverity = null;
  for (const iss of check.issues) {
    const where = iss.where || "";
    const owner = where.split(":")[0];
    if (owner === beatId || where.startsWith(beatId + ":") || where === beatId) {
      if (iss.severity === "error") return "error";
      sev = "warn";
    }
  }
  return sev;
}

export function Sidebar({ project, activeBeatId, check, onSelect }: Props) {
  return (
    <aside class="sidebar">
      <h3>Beats · {project.beats.length}</h3>
      {project.beats.map((b: ProjectBeat) => {
        const sev = beatSeverity(check, b.id);
        return (
          <div
            key={b.id}
            class={
              "beat-item" +
              (b.id === activeBeatId ? " active" : "") +
              (b.rendered ? " rendered" : "")
            }
            onClick={() => onSelect(b.id)}
          >
            <span class="mark" title={b.rendered ? "rendered" : "not rendered"} />
            <span class="main">
              <div class="id">{b.id}</div>
              <div class="title">{b.title || b.id}</div>
            </span>
            <span class="chips">
              {sev === "error" && <span class="chip err" title="check errors">!</span>}
              {sev === "warn" && <span class="chip warn" title="check warnings">?</span>}
              <span class="chip dur">{fmtDuration(b.duration)}</span>
            </span>
          </div>
        );
      })}
    </aside>
  );
}
