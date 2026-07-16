import type { BeatFeedback, ReviewSection, ReviewSuggestion } from "../api/types";

interface Props {
  beatId: string;
  feedback: BeatFeedback | undefined;
}

function verdictClass(verdict: string): string {
  const v = verdict.toLowerCase();
  if (v.includes("ship") || v.includes("final") || v.includes("in-final"))
    return "ship";
  if (v.includes("re-record") || v.includes("rerecord")) return "rerecord";
  return "rerender";
}

function sevClass(sev: string): string {
  const s = sev.toLowerCase();
  if (s.startsWith("crit")) return "crit";
  if (s.startsWith("high")) return "high";
  if (s.startsWith("low")) return "low";
  return "med";
}

function catClass(cat: string): string {
  const c = cat.toLowerCase().replace(/[^a-z]/g, "");
  if (c.includes("rerecord")) return "rerecord";
  if (c.includes("redesign")) return "redesign";
  return "mech";
}

function Suggestion({ s }: { s: ReviewSuggestion }) {
  return (
    <div class="suggestion">
      <div class="tags">
        <span class={"tag " + sevClass(s.severity || "med")}>
          {s.severity || "med"}
        </span>
        <span class={"tag " + catClass(s.category || "mech")}>
          {s.category || "mech"}
        </span>
        {s.effort && <span class="tag effort">{s.effort}</span>}
      </div>
      <div class="what">{s.what || "(no description)"}</div>
      {s.how && <div class="how">{s.how}</div>}
    </div>
  );
}

function Section({ name, data }: { name: string; data: ReviewSection }) {
  return (
    <div class="review-section">
      <h3>
        {name.toUpperCase()} review
        {data.timestamp && <span class="ts">{data.timestamp}</span>}
      </h3>
      {data.verdict && (
        <div class={"verdict " + verdictClass(data.verdict)}>
          <b>TL;DR:</b> {data.verdict}
        </div>
      )}
      {data.main_fix && (
        <p>
          <b>Main fix:</b> {data.main_fix}
        </p>
      )}
      {data.suggestions && data.suggestions.length > 0 && (
        <>
          {data.suggestions.map((s, i) => (
            <Suggestion key={i} s={s} />
          ))}
        </>
      )}
      {data.notes && <pre class="raw">{data.notes}</pre>}
      {data.raw && <pre class="raw">{data.raw}</pre>}
    </div>
  );
}

export function FeedbackPanel({ beatId, feedback }: Props) {
  if (!feedback || Object.keys(feedback).length === 0) {
    return (
      <div class="tab-body">
        <div class="empty">
          No feedback yet for <code>{beatId}</code>. Run <code>vo-reviewer</code>{" "}
          after recording or <code>video-reviewer</code> after rendering — their
          output appears here.
        </div>
      </div>
    );
  }
  return (
    <div class="tab-body feedback">
      {Object.entries(feedback).map(([section, data]) => (
        <Section key={section} name={section} data={data as ReviewSection} />
      ))}
    </div>
  );
}
