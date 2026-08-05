# Studio v3 — reel production hardening plan

## Goal

Improve the existing Studio v3 path so that a voice-led reel cannot reach review with a missing or silent voice track, and a passing review cannot freeze an incomplete publication package.

The target path remains:

```text
prepare → draft → final → review → package → deliver
```

No parallel runtime, compatibility reader, extra command bus, plugin framework, delivery bypass, or mutable post-delivery patching is introduced.

## Success criteria

1. A production with `Edit.voice_script` cannot pass `prepare` without an explicit `AudioClip(role="voice")`.
2. A structurally valid but digitally silent final MP4 cannot reach `review` when voice is required.
3. The rendered-artifact evidence is bound to exact `artifact sha256 + size`, persists in workflow outputs, and is part of review/release lineage.
4. `cover`, `metadata`, and any production-required publication files are immutable package inputs before review and freeze.
5. `ReviewVerdict` names the exact video evidence and exact publication manifest it approved.
6. `deliver` remains a read-only copy of one frozen `ReleaseCandidate`.
7. UI, HTTP, and CLI expose the same next useful action and the same blocking reason.

## Non-goals

- Do not automate uploading or publishing to social networks.
- Do not make review UI an editor for video or metadata.
- Do not infer an arbitrary recording as the selected voice take.
- Do not turn `WorkflowRun` into a task tracker.
- Do not put post-render signal analysis into the pure `TimelineIR + CheckPolicy -> CheckReport` contract.

## Architecture decisions

### A. Voice intent is checked before rendering

`Edit.voice_script` is the existing explicit authoring intent that the production has narration. `advance_production` passes that fact into the executable release gate. `CheckPolicy` gains `require_voice`; `check_timeline` emits blocking rule `audio.voice.required` when no voice instruction exists.

This catches the exact mistake from the short reel: a voice-bearing source was used only as a visual `MediaLayer` while `audio=()`.

The system does not auto-select a take. Authoring still explicitly names one immutable asset through `AudioClip`.

### B. Exact final media gets a separate rendering-owned report

Timeline checks remain pure and pre-render. A new canonical `ArtifactReport` belongs to `rendering` and is created only after the final file is ingested into the object store.

Minimum report fields:

- exact artifact `BlobRef`;
- width, height, fps, and duration;
- decoded audio stream facts;
- integrated loudness and true peak;
- active-audio ratio or equivalent non-silence evidence;
- canonical findings and blocking state.

`review` and `release` store only its `BlobRef`; they do not import `rendering`. Application use cases load and validate the report.

### C. Publication files become first-class immutable inputs

Authoring gains a small explicit `PublicationFile` intent:

```python
PublicationFile(
    role="cover",
    path="cover.png",
    asset_id="publish.cover.main",
)
```

The application resolves these logical asset IDs to exact `AssetRevision`s and builds a canonical release-owned `PublicationManifest`. It is included in prepare inputs/outputs, review context, review verdict, and release candidate.

Publication assets use the existing asset trust chain. Cover and metadata revisions must be approved and redistributable exactly like timeline media.

The generated final video and `licenses.json` remain release-owned outputs; they are not authored publication assets.

### D. Package requirements are executable constraints

The release gate uses stable constraint IDs:

- `audio.voice.required`;
- `package.cover.required`;
- `package.metadata.required`.

`check_timeline` owns the audio rule. `freeze_release` owns the package-role rules. The UI only presents their results.

### E. No mutation after pass

Any change to voice take, gain, timing, final artifact, cover, metadata, or publication asset revision invalidates downstream attempts. After a passing review, package only freezes the already reviewed refs. Delivery only copies and hashes them.

## Phase 1 — Voice intent and take readiness

### Implementation

1. Extend `CheckPolicy` with canonical `require_voice: bool`.
2. Make `build_release_gate` accept `require_voice` and add the matching `Constraint`.
3. Pass `bool(edit.voice_script and edit.voice_script.strip())` from `advance_production`.
4. Add pure `audio.voice.required` validation to `check_timeline`.
5. Add an application use case for explicitly approving a saved voice take using immutable recorder/script evidence.
6. Add an HTTP/UI action labelled `Использовать этот дубль`; it creates an approved revision and exposes the exact asset ID for authoring. It does not silently edit `EDIT`.
7. Show canonical save confirmation: take ID, state revision, current-script status, duration, approval state, and reload persistence.

### Primary files

- `common/dlstudio/src/dlstudio/timeline/api.py`
- `common/dlstudio/src/dlstudio/application/release.py`
- `common/dlstudio/src/dlstudio/application/production.py`
- `common/dlstudio/src/dlstudio/application/voice.py`
- `common/dlstudio/src/dlstudio/adapters/http.py`
- `common/dlstudio/webui/src/voice/VoiceRecorder.tsx`
- generated `common/dlstudio/webui/src/api/v3.gen.ts`

### Tests

- Voice script + no voice instruction blocks `prepare`.
- Intentional silent production with no voice script remains valid.
- Saved take survives full query/reload with the same `BlobRef`.
- Approving a stale-script take is rejected.
- Approved take produces a new exact revision with evidence and remains redistributable.
- UI never reports a local IndexedDB draft as a canonical saved take.

### Done when

A user can record, reload, explicitly approve a take, and an author cannot accidentally advance a narrated production whose exact timeline has no voice instruction.

## Phase 2 — Exact final artifact gate

### Implementation

1. Add canonical `ArtifactReport` and `verify_rendered_artifact` to `rendering.api`.
2. Run verification against the ingested final object, not the render source path or draft.
3. Verify geometry, fps, duration tolerance, decoded audio facts, loudness, true peak, and active audio when voice is required.
4. Make a blocking report fail the `final` attempt, so no review context is exposed.
5. Add `artifact_report` to the successful final output contract and bump the final operation contract version.
6. Bind the report ref through `ReviewVerdict`, review context, `ReleaseCandidate`, and freeze validation. Domain modules keep only `BlobRef` relations; application performs cross-module loading.
7. Show the report in review UI as read-only evidence: resolution, duration, audio status, loudness, peak, and exact hash.

### Primary files

- `common/dlstudio/src/dlstudio/rendering/api.py`
- `common/dlstudio/src/dlstudio/application/production.py`
- `common/dlstudio/src/dlstudio/application/workflow.py`
- `common/dlstudio/src/dlstudio/application/review.py`
- `common/dlstudio/src/dlstudio/review/api.py`
- `common/dlstudio/src/dlstudio/release/api.py`
- `common/dlstudio/src/dlstudio/application/release.py`
- `common/dlstudio/src/dlstudio/adapters/http.py`
- `common/dlstudio/webui/src/review/ReviewWorkspace.tsx`

### Tests

- Valid AAC stream containing digital silence blocks a voice-required final.
- Audible speech fixture passes.
- Intentionally silent production passes when voice is not required.
- Report artifact ref must equal the exact final artifact ref.
- Duration differs from timeline by at most one frame.
- Review cannot bind a stale or different artifact report.
- Package cannot use a report from another artifact.
- Any audio mutation creates a new final/report and requires a new verdict.

### Done when

The silent MP4 that previously reached delivery fails before review, while an audible exact final reaches review with visible evidence.

## Phase 3 — First-class publication package

### Implementation

1. Add explicit `PublicationFile` authoring type with `role`, normalized logical `path`, and `asset_id`.
2. Support publication data assets (`metadata.md` or canonical JSON) and image assets through the existing asset repository.
3. Resolve publication revisions in application code and create a canonical release-owned `PublicationManifest`.
4. Include the manifest and its exact revision refs in prepare inputs/outputs so changes invalidate draft/final/review/package.
5. Make `cover` and `metadata` required release roles for `kind="reel"`; explicit publication intent supplies their exact assets and paths. Existing v3 reel fixtures and productions must be updated rather than receiving a bypass flag.
6. Extend review context to show cover preview and metadata text; review remains read-only.
7. Bind the exact publication manifest in `ReviewVerdict` and require `publication` review scope when publication files are present.
8. Make `freeze_release` validate required roles, approval, redistribution, unique paths, exact refs, and include them beside `video.mp4` and generated `licenses.json`.
9. Include publication revisions in `ReleaseCandidate.asset_revisions` and reachable closure.
10. Keep `deliver` unchanged except for copying the larger frozen manifest.

### Primary files

- `common/dlstudio/src/dlstudio/authoring/api.py`
- `common/dlstudio/src/dlstudio/application/authoring.py`
- `common/dlstudio/src/dlstudio/application/production.py`
- `common/dlstudio/src/dlstudio/constraints/api.py`
- `common/dlstudio/src/dlstudio/release/api.py`
- `common/dlstudio/src/dlstudio/application/release.py`
- `common/dlstudio/src/dlstudio/review/api.py`
- `common/dlstudio/src/dlstudio/application/review.py`
- `common/dlstudio/src/dlstudio/adapters/http.py`
- `common/dlstudio/webui/src/review/ReviewWorkspace.tsx`

### Tests

- Missing required cover blocks review/freeze.
- Missing required metadata blocks review/freeze.
- Duplicate logical package paths are rejected.
- Pending or non-redistributable publication assets block release.
- Review verdict cannot be reused after metadata or cover revision changes.
- Frozen package contains exact reviewed video, cover, metadata, and generated licenses.
- Repeated delivery is idempotent and never patches an existing different destination.

### Done when

The exact package visible in Studio review is byte-for-byte the package copied by delivery, and a package containing only video plus licenses is impossible for a production that requires cover and metadata.

## Phase 4 — UI clarity and one-next-action flow

### Implementation

1. Voice page distinguishes local draft, canonically saved take, approved take, and take referenced by the current timeline.
2. Review page shows three evidence groups: video, audio report, publication files.
3. Blocking failures state the owner and next useful action, for example:
   - `Добавьте AudioClip с выбранным дублем`;
   - `Финальный звук не содержит слышимого сигнала`;
   - `Добавьте обязательную обложку`.
4. Delivery page lists every frozen file, size, and SHA-256 before destination confirmation.
5. Status remains a cheap projection and performs no media probing or authoring compilation.

### Tests

- Generated OpenAPI client is current and clean.
- UI component tests cover every new status and blocking state.
- HTTP and CLI expose equivalent workflow outcomes.
- Existing range playback, review lineage, and pending-delivery recovery remain intact.

### Done when

The user sees only the next useful action and can distinguish a saved recording, a selected voice layer, an audible final, a reviewed publication bundle, and a delivered package without inspecting the filesystem.

## Implementation order

```text
Slice 1: require_voice pre-render rule
Slice 2: ArtifactReport + silent-final blocking
Slice 3: report-bound exact review/release lineage
Slice 4: PublicationFile + PublicationManifest
Slice 5: package-bound review and immutable freeze
Slice 6: voice/review/delivery UI clarity
```

Each slice must remain releasable and pass the full cutover gate before the next begins.

## Validation after every runtime slice

```powershell
common\dlstudio\.venv\Scripts\python.exe -m tools.studio_v3_verify `
  --profile cutover --scope full --skip-toolchain
```

When HTTP/OpenAPI/UI changes:

```powershell
cd common\dlstudio\webui
npm run generate:client
npm test
npm run typecheck
npm run build
```

`src/api/v3.gen.ts` is regenerated, never edited manually.

## First implementation slice

Start with only `require_voice` and its regression tests. It is the smallest safe change, preserves every existing boundary, and immediately prevents the authoring error that produced the silent release. Do not combine it with publication packaging in the first commit.
