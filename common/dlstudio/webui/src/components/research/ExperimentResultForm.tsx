import { useState } from "preact/hooks";
import type {
  ExperimentResultInput,
  ExperimentVerdict,
  ResearchExperiment,
} from "../../api/research";

interface Props {
  experiment: ResearchExperiment;
  busy: boolean;
  onCancel: () => void;
  onSave: (input: ExperimentResultInput) => Promise<boolean>;
}

export function ExperimentResultForm({ experiment, busy, onCancel, onSave }: Props) {
  const [verdict, setVerdict] = useState<ExperimentVerdict>("worked");
  const [url, setUrl] = useState("");
  const [views, setViews] = useState("");
  const [likes, setLikes] = useState("");
  const [comments, setComments] = useState("");
  const [notes, setNotes] = useState("");

  async function submit(event: Event) {
    event.preventDefault();
    await onSave({
      verdict,
      published_url: url.trim(),
      views: Number(views || 0),
      likes: Number(likes || 0),
      comments: Number(comments || 0),
      notes: notes.trim(),
    });
  }

  return (
    <form class="experiment-result-form" onSubmit={submit}>
      <div class="experiment-composer-head">
        <div><span class="eyebrow">Close the loop</span><h3>What happened?</h3></div>
        <button type="button" class="btn sm secondary" onClick={onCancel}>Cancel</button>
      </div>
      <p class="hint">Measure our Reel made from experiment {experiment.id}.</p>
      <div class="experiment-result-fields">
        <label class="field-label">Verdict<select value={verdict} onChange={(event) => setVerdict(event.currentTarget.value as ExperimentVerdict)}><option value="worked">Worked</option><option value="mixed">Mixed</option><option value="did_not_work">Did not work</option><option value="inconclusive">Inconclusive</option></select></label>
        <label class="field-label result-url">Published Reel<input type="url" value={url} onInput={(event) => setUrl(event.currentTarget.value)} placeholder="https://www.instagram.com/reel/…" /></label>
        <label class="field-label">Views<input type="number" min="0" value={views} onInput={(event) => setViews(event.currentTarget.value)} /></label>
        <label class="field-label">Likes<input type="number" min="0" value={likes} onInput={(event) => setLikes(event.currentTarget.value)} /></label>
        <label class="field-label">Comments<input type="number" min="0" value={comments} onInput={(event) => setComments(event.currentTarget.value)} /></label>
        <label class="field-label result-notes">Learning notes<textarea rows={2} value={notes} onInput={(event) => setNotes(event.currentTarget.value)} placeholder="The opening worked, but the payoff arrived too late." /></label>
      </div>
      <button class="btn sm" disabled={busy}>{busy ? "Saving…" : "Save result to agent context"}</button>
    </form>
  );
}
