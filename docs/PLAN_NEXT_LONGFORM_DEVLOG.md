# Plan — next Not a Trolley Problem long-form devlog

Status: READY FOR TOPIC. No production has been created yet.

Goal: ship one 7–9 minute devlog whose story and montage are measurably
stronger than the 2026-07-17 and 2026-07-22 baselines.

Normative contract: `docs/LONGFORM_DEVLOG_SPEC.md`.
Current critique and competitor comparison:
`docs/LONGFORM_DEVLOG_AUDIT_2026-07-26.md`.
Production skill: `$dl-make-video`.

## Success criteria

The next episode is complete only when:

- one macro question is answered by the ending;
- 5–6 mini-arcs are identifiable by a blind reviewer;
- every mini-arc has visible before, failure/process, and payoff evidence;
- cold-open failure and payoff glimpse both begin before 0:08;
- the product and episode promise are spoken before 0:15;
- no undeclared semantic plateau exceeds 8 seconds;
- at least four visual modes are used for real editorial purposes;
- Russian VO is normally 150–165 wpm;
- author reaction/opinion/cost appears every 45–75 seconds;
- strict long-form, normal preflight, exact review, and delivery gates pass;
- thumbnail contains one real proof idea and no more than three words.

Views are an outcome metric, not an acceptance gate. Record CTR and retention
after 48 hours and 7 days.

## Phase 0 — preservation boundary

Owner: orchestrator.

The selected Yandex Disk policy is a **final publish archive**, not a source
backup. It stores the complete `data/publish/` plus the immutable delivery
bundle for every delivered production. It intentionally does not store raw
recordings, captures, caches, review frames, or working renders.

Tasks:

1. Do not clean, dedupe, move, or delete existing productions.
2. After every successful `dl2 deliver`, run:

   ```powershell
   py -3.12 tools/publish_archive.py --workspace . `
     --destination C:\Users\ROG\YandexDisk\Devlogs\projects
   ```

3. Treat an archive conflict as a blocker; never overwrite it silently.
4. Commit non-media controls separately from ignored media.

Exit:

- final publish archive is SHA-verified;
- source cleanup/migration remains forbidden until a separate full-project
  backup policy is approved.

Current status: PUBLISH ARCHIVE CONFIGURED. Seven existing packages are
archived. The 18.25 GiB working tree remains local-only, so storage cleanup is
still blocked; planning and production are not.

## Phase 1 — choose the episode

Owner: author; planner presents evidence, not invented product claims.

Required decision:

- one real development transformation with available or capturable failure
  and payoff.

Selection test:

| Candidate question | Failure exists? | Payoff can be shown? | 5 arcs available? | Viewer consequence? |
|---|---|---|---|---|
| `<candidate>` | yes/no | yes/no | yes/no | `<why it matters>` |

Reject a topic that is only “what I did this week”.

Exit:

- one-sentence macro question;
- one-sentence viewer promise;
- working title;
- 5–6 candidate mini-arcs.

Current status: NOT STARTED.

## Phase 2 — scaffold and evidence map

Owner: planner agent using `$dl-make-video`.

Command:

```powershell
dl2 new-production not_a_trolley_problem --kind devlog --date <YYYY-MM-DD>
```

Artifacts:

- `production.toml`;
- `data/plan/story_map.json`;
- `data/plan/shot_manifest.json`.

Tasks:

1. Fill macro question, cold open and ending.
2. Fill 5–6 complete story atoms.
3. Bind before/failure/process/payoff source paths.
4. Mark missing real captures `needs_capture`.
5. Draft montage shots with `arc_id`, `story_role`, `visual_mode`, `t0/t1`.
6. Plan 2 music phases and 8–12 purposeful SFX/stingers.

Gate:

```powershell
dl2 longform-check not_a_trolley_problem:<production>
```

Exit: 0 structural errors. `needs_capture` warnings are allowed.

## Phase 3 — capture

Owner: capture agent via `$devlog-record-media`; author approves exact
gameplay state.

Capture order:

1. cold-open failure;
2. cold-open payoff;
3. every mini-arc payoff;
4. every mini-arc failure;
5. process/editor/code/reference;
6. optional reaction/face material.

Each gameplay capture requires:

- exact state/build/action identity;
- real-time client-area stream;
- native landscape geometry;
- clean UI;
- 5-second head/tail handles;
- passing machine audit.

Exit:

```powershell
dl2 longform-check not_a_trolley_problem:<production> --strict
```

No final VO is recorded before this passes.

## Phase 4 — script and VO

Owner: planner drafts; author approves wording and records voice.

Script assembly:

```text
cold failure/payoff
→ context/stake
→ arc 1..N: goal, failure, cause, solution, proof, reaction
→ macro answer
→ honest status
→ one next question
```

Tasks:

1. Write to the shot evidence, not from a changelog.
2. Replace “потом я сделал” with concrete causality.
3. Keep one idea per spoken phrase.
4. Estimate 150–165 wpm, leaving proof/joke pauses.
5. Run hook review before final take.
6. Create hash-bound script approval.
7. Process and automatically speech-edit the recorded take.

Exit:

- approved script hash matches VO;
- proper names are correct in transcript tokens;
- flat/low-energy delivery has been re-recorded;
- no wording claims evidence that the montage cannot show.

## Phase 5 — montage and presentation

Owner: editing agent; motion designer only for a named explanatory need.

Assembly rules:

1. Build each arc as:
   `before → failure → cause/process → solution → payoff → reaction`.
2. Use comparable framing for failure/payoff.
3. Give clean payoff enough time to read without VO.
4. Change semantic state every 3–6 seconds.
5. For a shot over 8 seconds, declare internal change timestamps.
6. Default to hard cuts inside an arc; reserve short fades for chapter/time
   changes.
7. Use full-screen gameplay for proof.
8. Use editor/code only for cause or solution.
9. Use diagrams only for causality.
10. Keep overlays to one idea and normally 5–7 words.
11. Use at least four meaningful visual modes.
12. Mix two musical phases; duck/quiet at causes, jokes and first payoffs.

Artifacts:

- `edit/beats.py`;
- `ir.json`;
- final enriched `shot_manifest.json`;
- draft at `data/finalize/video.mp4`.

Exit:

```powershell
dl2 preflight not_a_trolley_problem:<production>
dl2 storyboard not_a_trolley_problem:<production>
```

Both pass before the author checkpoint.

## Phase 6 — blind improve loop

Owner: `video-reviewer`, blind by default.

Reviewer must provide:

- exact MP4 path and SHA-256;
- inferred macro question;
- failure/payoff timestamps for every identifiable arc;
- missing/unclear authored arcs;
- longest semantic plateau;
- music/VO/transition/ending findings;
- ranked top five fixes.

Loop:

```text
preview → blind review → safe fixes → preview
```

Limits:

- three iterations by default;
- five hard cap;
- structural or VO meaning changes return to the author.

Exit:

- reviewer identifies all 5–6 arcs without production notes;
- no blocking montage, proof, audio or ending issue;
- known-constraints regression passes separately.

## Phase 7 — final and package

Owner: orchestrator, reviewer, thumbnail designer, packager.

Commands:

```powershell
dl2 final not_a_trolley_problem:<production>
dl2 preflight not_a_trolley_problem:<production> --final
dl2 review-pack not_a_trolley_problem:<production>
dl2 publish-evidence not_a_trolley_problem:<production>
dl2 deliver not_a_trolley_problem:<production>
```

Package:

- exact reviewed `video.mp4`;
- `metadata.md`;
- real-proof `thumbnail.png`;
- `delivery_manifest.json`;
- three distinct title/thumbnail hypotheses for native YouTube A/B testing;
- attribution warning when required.

Exit:

- final SHA matches preflight, review and publish evidence;
- thumbnail/title match the first 15 seconds;
- deliberate ending verified;
- complete publish package is present in the append-only Yandex archive;
- one `devlog-reflector` report saved.

## Phase 8 — learning

At 48 hours and 7 days record:

- impressions;
- CTR;
- first-30-second retention;
- average percentage viewed;
- largest retention drops with timestamps;
- comments that reveal confusion or interest.

Compare against both existing devlogs. Change at most three production rules
for the next episode; do not optimize from view count alone.
