# Studio v3 — критика и convergence review плана review-системы

Date: 2026-07-30

Reviewed document:
[STUDIO-V3-REVIEW-SYSTEM-PLAN.md](./STUDIO-V3-REVIEW-SYSTEM-PLAN.md)

Method: three independent read-only reviews, followed by root synthesis:

1. architecture and source-grounding review;
2. product/UX and competitor-pattern critique;
3. implementation, migration, performance and test review.

## Verdict before revision

Direction: **correct**.

Implementation readiness: **not ready**.

All technical reviewers independently converged on four blocking gaps:

1. adding lineage fields directly to `ReviewVerdict.v3` has no legal schema
   evolution path under the no-compatibility-reader rule;
2. current `changes_requested` completes the review stage and makes `package`
   current, although packaging accepts only `pass`;
3. `review:latest` is not a reserved record and cannot be updated atomically
   with workflow completion using the current persistence operation;
4. serving previous artifacts needs a lineage-authorized application query,
   not a relaxed object-store endpoint.

The product reviewer separately found that the roadmap prioritised A/B before
proving the basic agent handoff, and that several team-review patterns were too
ceremonial for one owner.

## Converged technical findings

### HIGH — preserve `ReviewVerdict.v3`

Current facts:

- `ReviewVerdict.VERSION == 3`;
- its loader accepts one exact version;
- canonical reconstruction must be byte-identical;
- release identity names the exact verdict ref.

Adding optional lineage/resolution fields directly to its payload either
changes old v3 bytes or requires a runtime v3/v4 compatibility reader. Both
conflict with Studio v3 cutover rules.

Decision:

- keep `ReviewVerdict.v3` unchanged as the exact-artifact decision;
- introduce one new review-owned immutable `ReviewRound.v1` envelope for
  cross-artifact lineage and resolutions;
- keep lineage outside `ReleaseCandidate` identity and release trust closure;
- add byte-exact v3 golden fixtures and regression tests.

This is not a parallel review implementation. `ReviewVerdict` remains the
owner of the exact artifact verdict; `ReviewRound` owns the genuinely distinct
cross-version lifecycle.

### HIGH — non-pass cannot advance to package

Current behavior:

```text
submit changes_requested
        ↓
review attempt succeeds
        ↓
current stage = package
        ↓
package rejects non-pass verdict
```

Package failure must not be normal control flow.

Decision:

| Outcome | Review history | Workflow transition |
|---|---|---|
| `pass` | Commit verdict and round | Complete review; package becomes current |
| `changes_requested` | Commit verdict and round | Remain at review until changed authoring restarts prepare |
| `block` | Commit verdict and round | Remain at review; package is unavailable |

Only `pass` can become the workflow review-stage output used by release.

### HIGH — define resolution semantics across three or more rounds

`still_wrong` cannot be only a label on the previous finding. Otherwise the
next round has no current required finding to continue.

Decision:

- every resolution names the previous round and previous finding;
- `fixed` and `obsolete` close that previous finding;
- `still_wrong` must map to a required finding in the current exact-artifact
  verdict;
- application validation loads the previous round/verdict and enforces
  completeness, duplicates, existence and the truth table;
- `pass` permits only `fixed | obsolete`;
- `still_wrong` necessarily implies a non-pass verdict:
  `changes_requested | block`.

The UI may offer one owner-facing action, “Все исправления устраивают”, but the
canonical round still records explicit typed resolutions for every required
previous finding.

### HIGH — one owner-scoped CAS transaction

Decision:

- reserve `review:latest` beside `assets:index` and `workflow:current`;
- generic record mutation cannot write it;
- add one persistence operation for review completion;
- for `pass`, atomically publish the succeeded workflow snapshot and new round
  pointer;
- for non-pass, atomically advance only the round pointer while the workflow
  remains at review;
- verify expected workflow revision, head revision and previous round ref;
- crash before commit leaves the old pointer; retry is idempotent.

No review dependency is added to the workflow domain model.

### HIGH — authorize old media through lineage

The current artifact endpoint validates only the current context. It must not
be changed into a generic blob reader.

Decision:

- application walks exact `ReviewRound` refs from `review:latest`;
- each round loads its exact verdict;
- old timeline identity is recovered through
  `verdict.check_report -> CheckReport.timeline`;
- only artifacts in this bounded, cycle-free chain are authorized;
- cached verification is keyed by head/latest-round identity;
- the requested old `BlobRef`, never `context.artifact`, selects the file;
- unrelated object-store blobs remain unavailable.

## Product/UX critique and decisions

### Accepted — prove one complete agent loop first

Before building lineage or comparison, run one real:

```text
comment → structured handoff → source change → render → new review
```

This reveals whether `target_ids` are sufficient for the agent or whether a
source mapping is actually required.

### Accepted with constraint — improve agent locatability

The task pack should expose:

- exact verdict/context refs;
- target snapshots and human labels;
- frame/range/region;
- local authoring hint when one can be derived safely;
- otherwise explicit `source_mapping: unavailable`.

A local source path or compile map is a noncanonical agent projection. It must
not enter `TimelineIR`, render identity or `ReviewVerdict`.

If the proof loop shows repeated search failures, design an authoring-owned
compile map as a separate proposal. Do not invent it pre-emptively.

### Accepted — simplify resolution UI

Canonical resolution remains explicit, but default owner UX is:

- “Все исправления устраивают”;
- mark only exceptions as “Всё ещё не так” or “Не актуально”;
- create a new locator only for an exception.

This preserves correctness without reproducing a team issue tracker.

### Accepted — narrow A/B

First release:

- per-finding `До` hold/toggle;
- independent exact labels for old and current versions;
- no canonical time remapping.

Side-by-side, linked playback across full videos and overlay comparison move
behind usage evidence.

### Accepted — narrow audio work

Start with one final-mix waveform experiment. Role-specific waveforms,
transition density and multi-lane review remain deferred unless real reviews
show repeated audio-location failures.

### Deferred — immediate canonical comment submission

The reviewer proposed replacing local draft + final submit with immediate
canonical comments. The current `ReviewVerdict` is terminal for one exact
review, so immediate submission would require a separate server-side draft
lifecycle.

Decision: keep the explicit batch boundary for now. Measure abandonment or
missed submission in real use before adding another canonical entity.

### Deferred — mobile bottom sheet

The current responsive implementation is usable and overflow-free, but still
has vertical travel. Add a measurable mobile task-flow check to the A/B slice.
Build a bottom sheet only if real review tasks exceed the agreed interaction
or scroll budget.

### Rejected pending evidence — downgrade the existing 21/24 UI score

The product reviewer challenged the score because technical labels remain
available. The full timeline is collapsed and active audio chips already use
human role labels. The score should not change without a new observed
usability run against the current implementation.

## Competitor patterns through the actual persona

| Reference | Owner effort | Agent actionability | Take | Do not take |
|---|---|---|---|---|
| [Frame.io](https://help.frame.io/en/articles/9105251-commenting-on-your-media) | Direct frame/range/anchor feedback | Strong structured export/API | Range handles, anchored feedback, per-finding compare | Team/DAM/notification model |
| [Dropbox Replay](https://help.dropbox.com/view-edit/dropbox-replay-feedback) | Simple `Post` flow and drawing | Export-oriented handoff | Plain-language review and portable JSON | Cloud upload as required step |
| [SyncSketch](https://support.syncsketch.com/hc/en-us/articles/32393850754196-Timeline-Navigation-and-Playback-Controls) | VFX-oriented controls | CSV; deeper API on higher tier | A/B toggle and waveform navigation | Dense VFX timeline |
| [Kitsu](https://kitsu.cg-wire.com/review/) | Web review plus production statuses | Strong API/data model | Structured annotations and agent-readable context | Production tracking and AGPL sidecar |
| [xSTUDIO](https://github.com/AcademySoftwareFoundation/xstudio) | Local desktop frame/range notes | CSV/JPEG; developing vector API | Local-first exact review concepts | Desktop embedding/build stack |
| [OpenRV](https://github.com/AcademySoftwareFoundation/OpenRV) | Powerful professional viewer | Session/OTIO, no verdict lifecycle | Playback and wipe ideas | Viewer toolkit as product core |
| [HyperFrames](https://github.com/heygen-com/hyperframes) | Full source-editing Studio | Excellent transient element selection | Stable element ID/source-context protocol | Full editor inside owner review |

No competitor controls both ends of this workflow. Studio does. Therefore an
internal canonical query is more valuable than import/export adapters.

## Verification additions required by the review

Contract:

- byte-exact `ReviewVerdict.v3` fixture;
- `ReviewRound.v1` round-trip and deterministic hash;
- three rounds: `still_wrong -> still_wrong -> fixed`;
- unknown, duplicate and missing resolutions;
- `pass + still_wrong` rejected.

Persistence:

- workflow and latest-round pointer commit atomically;
- crash/retry/reopen;
- upstream invalidation preserves latest round;
- generic update cannot write the reserved key.

Authorization:

- current and historical GET/HEAD/206;
- unrelated blob denied;
- wrong hash/size denied;
- cycle/corruption rejected;
- cached old URL cannot return current bytes.

UI:

- “accept all / mark exceptions” state machine;
- per-finding old/current labels;
- different FPS/duration clamping;
- keyboard and mobile task flow;
- no horizontal overflow.

Performance:

- bounded lineage walk for 100+ rounds;
- cache invalidation on latest-round change;
- cold/warm Range first-seek;
- bounded process-local verification cache;
- no FFmpeg work under writer lease.

## Convergence status

Before revision:

```text
architecture review: 4 HIGH, 8 actionable
implementation review: 4 HIGH, 9 actionable
product/UX review: 6 P1, 9 actionable
```

First recheck after the main revision:

```text
architecture recheck: 0 HIGH, 2 actionable
implementation recheck: 0 HIGH, 8 actionable
product/UX recheck: 0 HIGH, 0 actionable
```

After the remaining contract, persistence, authorization, browser-test and
performance details were added, the independent final recheck reported:

```text
final architecture recheck: 0 HIGH, 0 actionable
final implementation recheck: 0 HIGH, 0 actionable
```

The plan has therefore converged:

```text
current_high = 0
current_actionable = 0
```
