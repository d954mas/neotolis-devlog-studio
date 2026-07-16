import { useState } from "preact/hooks";
import type { Timeline } from "../api/types";
import { JsonTree } from "./JsonTree";
import { MixTimeline } from "./MixTimeline";

interface Props {
  ir: Timeline | null;
  error?: string | null;
  activeBeatId: string | null;
}

type Scope = "timeline" | "beat" | "mix";

export function IRInspector({ ir, error, activeBeatId }: Props) {
  const [scope, setScope] = useState<Scope>("timeline");

  if (error) {
    return (
      <div class="tab-body">
        <div class="empty err-text">IR unavailable: {error}</div>
      </div>
    );
  }
  if (!ir) {
    return (
      <div class="tab-body">
        <div class="empty">Loading IR…</div>
      </div>
    );
  }

  const beat = ir.beats.find((b) => b.id === activeBeatId) || null;
  const jsonData =
    scope === "beat" ? (beat ?? { note: "no beat selected" }) : scope === "mix" ? ir.mix : ir;

  return (
    <div class="tab-body">
      <div class="ir-inspector">
        <div>
          <div class="ir-section-title">Mix timeline</div>
          <MixTimeline ir={ir} />
        </div>

        <div>
          <div class="ir-section-title">
            Timeline IR
            <div class="tabs" style={{ marginLeft: "auto" }}>
              <span
                class={"tab" + (scope === "timeline" ? " active" : "")}
                onClick={() => setScope("timeline")}
              >
                Full
              </span>
              <span
                class={"tab" + (scope === "beat" ? " active" : "")}
                onClick={() => setScope("beat")}
              >
                Beat{activeBeatId ? ` · ${activeBeatId}` : ""}
              </span>
              <span
                class={"tab" + (scope === "mix" ? " active" : "")}
                onClick={() => setScope("mix")}
              >
                Mix
              </span>
            </div>
          </div>
          <JsonTree data={jsonData} defaultOpenDepth={scope === "timeline" ? 1 : 2} />
        </div>
      </div>
    </div>
  );
}
