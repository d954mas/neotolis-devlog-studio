import { useState } from "preact/hooks";
import type { ExperimentInput, ExperimentMode, ResearchReel } from "../../api/research";

interface Props {
  reel: ResearchReel;
  busy: boolean;
  onCancel: () => void;
  onCreate: (input: ExperimentInput) => Promise<boolean>;
}

const MODES: Array<{ id: ExperimentMode; label: string; help: string }> = [
  { id: "inspiration", label: "Inspiration", help: "Borrow an observation or topic." },
  { id: "adaptation", label: "Adaptation", help: "Test the pattern in your own style." },
  { id: "remake", label: "Remake", help: "Follow the structure closely and deliberately." },
];

function splitList(value: string): string[] {
  return value.split(/[,\n]/).map((item) => item.trim()).filter(Boolean);
}

export function ExperimentComposer({ reel, busy, onCancel, onCreate }: Props) {
  const [mode, setMode] = useState<ExperimentMode>("adaptation");
  const [hypothesis, setHypothesis] = useState("");
  const [take, setTake] = useState(reel.patterns.join(", "));
  const [keep, setKeep] = useState("our footage, our voice, our visual style");

  async function submit(event: Event) {
    event.preventDefault();
    await onCreate({
      reel_id: reel.id,
      mode,
      hypothesis,
      take_from_reference: splitList(take),
      keep_original: splitList(keep),
    });
  }

  return (
    <form class="experiment-composer" onSubmit={submit}>
      <div class="experiment-composer-head">
        <div>
          <span class="eyebrow">New experiment</span>
          <h3>What are we testing?</h3>
        </div>
        <button type="button" class="btn sm secondary" onClick={onCancel}>Cancel</button>
      </div>

      <fieldset class="experiment-modes">
        <legend>Similarity to the reference</legend>
        {MODES.map((item) => (
          <label key={item.id} class={`experiment-mode ${mode === item.id ? "selected" : ""}`}>
            <input
              type="radio"
              name={`mode-${reel.id}`}
              value={item.id}
              checked={mode === item.id}
              onChange={() => setMode(item.id)}
            />
            <span><b>{item.label}</b><small>{item.help}</small></span>
          </label>
        ))}
      </fieldset>

      <label class="field-label">
        Hypothesis
        <textarea
          rows={2}
          value={hypothesis}
          onInput={(event) => setHypothesis(event.currentTarget.value)}
          placeholder="Showing the broken mechanic in the first second will make the story clearer."
        />
      </label>
      <div class="experiment-fields">
        <label class="field-label">
          Take from reference
          <textarea rows={2} value={take} onInput={(event) => setTake(event.currentTarget.value)} />
        </label>
        <label class="field-label">
          Keep original
          <textarea rows={2} value={keep} onInput={(event) => setKeep(event.currentTarget.value)} />
        </label>
      </div>
      <button class="btn" type="submit" disabled={busy}>
        {busy ? "Creating…" : "Create experiment"}
      </button>
    </form>
  );
}
