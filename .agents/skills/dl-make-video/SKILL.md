---
name: dl-make-video
description: Produce or revise a Studio v2 devlog, reel, short, or YouTube video from an approved script/VO and product assets, with product-scoped manifests, deterministic preflight, one consolidated checkpoint, blind review, final render, delivery bundle, telemetry, and reflection. Use when a user asks to make, automate, finish, review, or package a video in the devlogs workspace, especially under a time budget.
---

# DL Make Video

Run the production as a deadline-aware state machine. Keep the FFmpeg Studio v2
pipeline authoritative; HyperFrames may only create motion/infographic inputs.

## Start

1. Read the workspace `AGENTS.md` and `docs/QUICKSTART_V2.md`.
2. Resolve or create `product.toml` and one dated `production.toml`.
   For `kind=devlog`, first read
   `docs/LONGFORM_DEVLOG_AUDIT_2026-07-26.md`, then
   `docs/LONGFORM_DEVLOG_SPEC.md`; the audit defines the current gap and the
   spec turns it into executable gates rather than optional planning notes.
3. Read `shared/preferences.toml`, the production brief, script approval, and
   only the assets/review artifacts needed for this production.
4. Record the target wall time and human-time budget. Start production telemetry.

Do not load the full conversation into production roles. Use at most three narrow
roles: planner, blind reviewer, packager. Give each raw artifacts and minimal
context. Use no synthetic version of the creator's voice without explicit approval.

## State machine

Progress only in this order:

`brief → script_approved → vo_ready → assets_ready → shot_plan_ready → storyboard_passed → final_passed → delivered → metrics_pending`

For `kind=devlog`, `brief → script_approved` additionally requires a passing
planning `dl2 longform-check`. Before final VO, `dl2 longform-check --strict`
must pass so every promised failure/process/payoff is bound to an existing
source.

Stop early with one consolidated request if final VO or a critical real-product
capture is missing. Never substitute a fake product visual when the claim promises
the game, Studio, Steam page, Canvas, or Diary.

## Produce

1. Run `dl2 inventory <product:production>`.
   For every reel, write a one-sentence `standalone_story` contract before the
   shot ledger: the opening must identify the product/situation without prior
   episodes, the middle must carry one complete causal turn, and the ending
   must resolve that turn. Treat “part 2”, “а ещё”, “теперь” and unexplained
   callbacks as blockers unless the same reel supplies their context.
   For a devlog, fill `data/plan/story_map.json` first: one macro question,
   a real failure/payoff cold open, and at least
   `max(4, ceil(duration / 90s))` completed mini-arcs.
2. Create `data/plan/shot_manifest.json`: cover every VO claim; mark proof source,
   duration, presentation, reuse policy, motion, and approval.
   For a devlog, every shot also names `arc_id`, `story_role`, and
   `visual_mode`. Every arc needs before, payoff, and failure/process montage
   coverage. A master shot over 8 seconds declares internal semantic changes
   with no gap above 6 seconds.
   For missing real-time gameplay or VO, invoke `$devlog-record-media` before
   accepting the asset. For a controlled game-owned testbed/presentation scene,
   invoke `$devlog-debug-scenes` and keep its role `debug_proof` or
   `presentation`. A frame-stepped DevAPI artifact never satisfies a gameplay
   request.
3. Run `dl2 preflight <product:production>`. Resolve blockers before rendering.
4. Run `dl2 storyboard <product:production>` once. Inspect the contact sheet,
   keyframes, and ±0.25 s around every boundary.
5. Present one checkpoint only when a human decision is truly required. Consolidate
   script, sources, captures, and disputed claims into the same request.
6. Apply safe visual/source/timing fixes without changing meaning. Re-preview at
   most three iterations by default, five hard cap.
7. Run a blind reviewer on the exact MP4. Persist artifact path, SHA-256, timestamp,
   verdict, and timestamped findings in `data/review/feedback.json`.
8. Run known-constraints regression separately from blind review.
9. Run `dl2 final <product:production>` only after the storyboard gate passes.
10. Recompute the hash; any earlier review is stale after the final changes. Review
    the exact delivery candidate or perform an exact regression pass.
11. Run `dl2 publish-evidence <product:production>` and verify that the exact
    reviewed final is materialized beside the metadata as
    `data/publish/video.mp4`. Then run `dl2 deliver <product:production>`. Verify
    `video.mp4`, `metadata.md`, and
    `thumbnail.png` or `cover.png` plus `delivery_manifest.json`.
12. Archive the complete final publish package:
    `py -3.12 tools/publish_archive.py --workspace . --destination
    C:\Users\ROG\YandexDisk\Devlogs\projects`. A conflict blocks handoff;
    never overwrite or delete an archived package.
13. Spawn the workspace `devlog-reflector` exactly once and save its timestamped
    report under `data/review/reflections/`.

For vertical work, read and execute `docs/CHECKLIST_VERTICAL_REEL.md` section A in
full before final. A landscape source is allowed only as an explicit framed/inset/
contain/split composition; never crop/upscale it to silence VQ-RES.

## Gates

Treat unverified as not passed. Block on missing/broken assets, transcript indices,
upscale, unapproved script, invalid hashtags, wrong source role, unreadable text,
too-short proof, and missing delivery files. Inspect warnings about VO start noise,
long static holds, callbacks, frame occupancy, boundaries, and motion smoothness.
Block gameplay ingest when capture method, state/build identity, native client-area
geometry, 5-second head/tail handles, or the machine audit report is missing.
For devlogs, block final VO and final preflight when the strict long-form gate
has unresolved sources, missing arc proof, an unbound montage source, or an
unplanned master-shot plateau.
Validate source/crop geometry and IR first; use visual review afterward for subject
emphasis, labels, text, and style.

Preserve the creator's voice profile: first-person singular, short spoken sentences,
one idea per phrase, no AI clichés, and canonical brand spellings. Captions belong in
the lower-middle safe band and every ending must have a deliberate hold.

Do not put internal production labels such as `REEL 01`, `REEL 02`, `VERSION B`,
or edit ids on screen. A public episode/series label is allowed only when the user
explicitly requested a serialized identity; it never relaxes the standalone-story
gate.

## Output and handoff

Delivery is production-scoped under the product root. Metadata must keep YouTube
keyword tags separate from copy-ready hashtag tokens. Include license attribution
as a blocking handoff warning only when required.

Report exact paths and hashes, runtime/resolution/loudness, gates passed, remaining
judgment calls, wall/human/render time, and stage-attributed token counts. Never call
the whole task tree “tokens for the video.”
For devlogs, also report the inferred macro question, mini-arc count, proof
coverage, longest semantic plateau, exact strict-gate artifact, and publish
archive result.

Read [production-contract.md](references/production-contract.md) when creating or
validating manifests, shot ledgers, delivery files, or telemetry.
