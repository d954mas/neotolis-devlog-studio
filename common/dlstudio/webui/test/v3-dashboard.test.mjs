import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
import test from "node:test";

const app = await readFile(new URL("../src/app.tsx", import.meta.url), "utf8");
const workflowDashboard = await readFile(
  new URL("../src/WorkflowDashboard.tsx", import.meta.url),
  "utf8",
);
const reviewWorkspace = await readFile(
  new URL("../src/review/ReviewWorkspace.tsx", import.meta.url),
  "utf8",
);
const reviewPlayer = await readFile(
  new URL("../src/review/ReviewPlayer.tsx", import.meta.url),
  "utf8",
);
const reviewTimeline = await readFile(
  new URL("../src/review/ReviewTimeline.tsx", import.meta.url),
  "utf8",
);
const reviewNotes = await readFile(
  new URL("../src/review/ReviewNotes.tsx", import.meta.url),
  "utf8",
);
const previousFindingsReview = await readFile(
  new URL(
    "../src/review/PreviousFindingsReview.tsx",
    import.meta.url,
  ),
  "utf8",
);
const frameStrip = await readFile(
  new URL("../src/review/FrameStrip.tsx", import.meta.url),
  "utf8",
);
const reviewTimeTrack = await readFile(
  new URL("../src/review/ReviewTimeTrack.tsx", import.meta.url),
  "utf8",
);
const useReviewWaveform = await readFile(
  new URL("../src/review/useReviewWaveform.ts", import.meta.url),
  "utf8",
);
const waveformShape = await readFile(
  new URL("../src/review/WaveformShape.tsx", import.meta.url),
  "utf8",
);
const findingRegionEvidence = await readFile(
  new URL("../src/review/FindingRegionEvidence.tsx", import.meta.url),
  "utf8",
);
const voiceRecorder = await readFile(
  new URL("../src/voice/VoiceRecorder.tsx", import.meta.url),
  "utf8",
);
const voiceDraftStore = await readFile(
  new URL("../src/voice/draftStore.ts", import.meta.url),
  "utf8",
);
const deliveryContextHook = await readFile(
  new URL("../src/delivery/useDeliveryContext.ts", import.meta.url),
  "utf8",
);
const ui = [
  app,
  workflowDashboard,
  reviewWorkspace,
  reviewPlayer,
  reviewTimeline,
  reviewNotes,
  previousFindingsReview,
  frameStrip,
  reviewTimeTrack,
  useReviewWaveform,
  waveformShape,
  findingRegionEvidence,
  voiceRecorder,
  voiceDraftStore,
  deliveryContextHook,
].join("\n");
const http = await readFile(
  new URL("../../src/dlstudio/adapters/http.py", import.meta.url),
  "utf8",
);

test("dashboard uses only the generated Studio v3 client surface", () => {
  assert.match(app, /from "\.\/api\/v3\.client"/);
  assert.match(app, /studioV3\.GET\("\/api\/v3\/status"\)/);
  for (const path of ["advance", "review", "deliver"]) {
    assert.match(ui, new RegExp(`studioV3\\.POST\\("\\/api\\/v3\\/${path}"`));
  }
  for (const banned of ["/api/file", "pollJob", "job_id", "/api/project", "/research/"]) {
    assert.doesNotMatch(ui, new RegExp(banned));
  }
});

test("review and delivery controls are stage-gated", () => {
  assert.match(app, />\s*Start production\s*<\/button>/);
  assert.match(workflowDashboard, /status\.action === "advance"/);
  assert.match(app, /status\?\.action === "review"/);
  assert.match(app, /currentReview\.artifact/);
  assert.match(app, /stage === "review" \|\| stage === "package"/);
  assert.match(workflowDashboard, /stage === "review"/);
  assert.match(workflowDashboard, /status\.action === "deliver"/);
  assert.doesNotMatch(app, /const STAGES|function currentStage/);
  assert.ok(app.split(/\r?\n/).length <= 200, "app.tsx must stay understandable");
});

test("review surface captures exact frame, range, region and TimelineIR targets", () => {
  assert.match(reviewWorkspace, /end_frame_exclusive/);
  assert.match(reviewWorkspace, /target_ids: activeTargets/);
  assert.match(reviewWorkspace, /expected_artifact: context\.artifact/);
  assert.match(reviewWorkspace, /expected_timeline: context\.timeline/);
  assert.match(
    reviewWorkspace,
    /expected_latest_round: context\.latest_round/,
  );
  assert.match(reviewWorkspace, /context\.latest_verdict/);
  assert.match(reviewWorkspace, /\bresolutions,/);
  assert.match(reviewWorkspace, /unresolved/);
  assert.match(reviewWorkspace, /still_wrong/);
  assert.match(previousFindingsReview, /obsolete/);
  assert.match(
    reviewWorkspace,
    /outcome === "pass" && status === "still_wrong"/,
  );
  assert.match(
    reviewWorkspace,
    /status === "unresolved"/,
  );
  assert.doesNotMatch(app, /previousReview={currentReview}/);
  assert.match(reviewWorkspace, /nsToFrameCeil\(item\.start_ns/);
  assert.doesNotMatch(reviewWorkspace, /\bnsToFrame\(/);
  assert.match(reviewWorkspace, /studioV3\.GET\("\/api\/v3\/review\/context"\)/);
  assert.doesNotMatch(reviewWorkspace, /selectionMode|rangeAnchor|rangeEdge/);
  assert.match(reviewTimeTrack, /onPointerDown={handlePointerDown}/);
  assert.match(reviewTimeTrack, /onPointerMove={handlePointerMove}/);
  assert.match(reviewTimeTrack, /event\.button !== 0 \|\| !event\.isPrimary/);
  assert.match(reviewTimeTrack, /onLostPointerCapture=/);
  assert.match(reviewTimeTrack, /setDragSelection/);
  assert.match(frameStrip, /captureRequest/);
  assert.match(reviewTimeTrack, /role="slider"/);
  assert.match(frameStrip, /aria-pressed={selected}/);
  assert.match(reviewPlayer, /onPointerDown={startRegion}/);
  assert.doesNotMatch(reviewPlayer, /setDrawing|selectionMode/);
  assert.match(reviewPlayer, /event\.target !== event\.currentTarget/);
  assert.match(reviewPlayer, /aria-label="На один кадр назад"/);
  assert.match(reviewPlayer, /toggleMute/);
  assert.match(reviewPlayer, /toggleFullscreen/);
  assert.match(reviewPlayer, /onCurrentMediaState\("error"\)/);
  assert.match(reviewTimeline, /Слои, переходы и звук/);
  assert.match(reviewTimeline, /activeTargets\.includes\(item\.item_id\)/);
  assert.doesNotMatch(reviewTimeline, /onToggleTarget/);
  assert.match(reviewNotes, /hasUnsavedNote/);
  assert.match(reviewNotes, /role="status"/);
});

test("presentation aids are exact, bounded, cached, and never become review facts", () => {
  assert.match(
    useReviewWaveform,
    /studioV3\s*\.GET\("\/api\/v3\/review\/artifacts\/\{sha256\}\/waveform"/,
  );
  assert.match(useReviewWaveform, /sha256.*size.*sampleCount/s);
  assert.match(useReviewWaveform, /waveformCache/);
  assert.match(useReviewWaveform, /inFlight/);
  assert.match(useReviewWaveform, /retry/);
  assert.match(useReviewWaveform, /expectedDurationNs/);
  assert.match(useReviewWaveform, /state\.key !== key/);
  assert.match(waveformShape, /<path/);
  assert.doesNotMatch(waveformShape, /\.map\([^)]*=>\s*<rect/);
  assert.match(waveformShape, /aria-hidden="true"/);
  assert.match(frameStrip, /reviewFrameEvidenceUrl/);
  assert.doesNotMatch(frameStrip, /document\.createElement\("video"\)/);
  assert.doesNotMatch(frameStrip, /canvas|toDataURL|drawImage/);
  assert.match(reviewTimeTrack, /mode === "select"/);
  assert.match(reviewTimeTrack, /mode === "seek"/);
  assert.match(reviewTimeTrack, /version === "previous"/);
  assert.match(reviewTimeTrack, /aria-describedby=/);
  assert.match(reviewTimeTrack, /time-range-marker/);
  assert.match(frameStrip, /failedFrames\.size > 0/);
  assert.match(frameStrip, /frameRequestKey/);
  assert.match(frameStrip, /currentRequestKey/);
  assert.match(reviewPlayer, /<ReviewTimeTrack/);
  assert.match(reviewPlayer, /mode="seek"/);
  assert.match(findingRegionEvidence, /reviewFrameEvidenceUrl/);
  assert.match(findingRegionEvidence, /loading="lazy"/);
  assert.match(previousFindingsReview, /<FindingRegionEvidence/);
  assert.match(previousFindingsReview, /key={finding\.finding_id}/);
  assert.doesNotMatch(
    [
      reviewTimeTrack,
      useReviewWaveform,
      waveformShape,
      findingRegionEvidence,
    ].join("\n"),
    /localStorage|ReviewVerdict|expected_artifact/,
  );
});

test("repeat review compares the exact old artifact and marks only exceptions", () => {
  assert.match(
    reviewWorkspace,
    /studioV3\.GET\("\/api\/v3\/review\/task-pack"\)/,
  );
  assert.match(reviewWorkspace, /sameBlobRef/);
  assert.match(reviewWorkspace, /previousPack\.artifact/);
  assert.match(reviewWorkspace, /result\.data\.latest_round/);
  assert.match(reviewWorkspace, /showingOld/);
  assert.match(previousFindingsReview, /onPointerDown/);
  assert.match(previousFindingsReview, /onPointerUp/);
  assert.match(previousFindingsReview, /onPointerCancel/);
  assert.match(previousFindingsReview, /onKeyDown/);
  assert.match(previousFindingsReview, /onKeyUp/);
  assert.match(previousFindingsReview, /Удерживайте.*До/);
  assert.match(previousFindingsReview, /Прошлое замечание/);
  assert.match(previousFindingsReview, /Всё ещё не так/);
  assert.match(previousFindingsReview, /Больше не актуально/);
  assert.match(reviewPlayer, /comparisonLabel/);
  assert.match(reviewPlayer, /readOnly/);
  assert.match(reviewPlayer, /function activeVideo/);
  assert.match(reviewPlayer, /wasPlayingBeforeComparison/);
  assert.match(reviewPlayer, /activeVideo\.volume = currentVideo\.volume/);
  assert.match(reviewWorkspace, /focusPreviousOnCurrent/);
  assert.match(
    reviewWorkspace,
    /comparison === null\s*\|\|\s*comparison\.sameMedia/,
  );
  assert.match(
    reviewWorkspace,
    /linkedPreviousIndex = previousFindings\.findIndex/,
  );
  assert.match(reviewWorkspace, /legacyDraftStorageKey/);
  assert.match(reviewWorkspace, /activePreviousIndex,\s+note,\s+selection,\s+region/);
  assert.match(reviewWorkspace, /canRestorePending/);
  assert.match(reviewWorkspace, /DRAFT_STORAGE_WARNING/);
  assert.match(reviewWorkspace, /if \(statusResult\.data\) \{\s+onSubmitted/);
  assert.match(app, /currentReview\.check_report/);
  assert.match(app, /currentReview\.constraints/);
});

test("legacy component, manual API, job and file surfaces are gone", async () => {
  const apiFiles = await readdir(new URL("../src/api/", import.meta.url));
  const sourceFiles = await readdir(
    new URL("../src/", import.meta.url),
    { recursive: true },
  );
  assert.deepEqual(
    apiFiles.sort(),
    ["openapi.v3.json", "v3.client.ts", "v3.gen.ts"].sort(),
  );
  assert.equal(
    sourceFiles.some(
      (path) => /(^|[\\/])components[\\/]research[\\/].+\.[cm]?[jt]sx?$/.test(path),
    ),
    false,
  );
  assert.equal(
    sourceFiles.some(
      (path) => /(^|[\\/])lib[\\/].+\.[cm]?[jt]sx?$/.test(path),
    ),
    false,
  );
});

test("FastAPI serves the dashboard outside the OpenAPI route set", () => {
  assert.match(http, /app\.get\("\/", include_in_schema=False\)/);
  assert.match(http, /app\.mount\(\s*"\/assets"/);
  assert.doesNotMatch(http, /@app\.get\("\/api\/file/);
});

test("voice recording survives refresh and becomes immutable only after save", () => {
  assert.match(voiceRecorder, /studioV3\.GET\("\/api\/v3\/voice"\)/);
  assert.match(voiceRecorder, /saveVoiceDraft/);
  assert.match(voiceRecorder, /loadVoiceDraft/);
  assert.match(voiceRecorder, /deleteVoiceDraft/);
  assert.match(voiceRecorder, /\/api\/v3\/voice\/takes\?expected_revision=/);
  assert.match(voiceRecorder, /ВОССТАНОВЛЕННЫЙ ЧЕРНОВИК/);
  assert.match(voiceDraftStore, /indexedDB\.open/);
  assert.match(voiceDraftStore, /productionId/);
  assert.match(voiceDraftStore, /scriptRef/);
  assert.match(voiceRecorder, /X-Production-Id/);
  assert.match(voiceRecorder, /X-Script-Sha256/);
  assert.doesNotMatch(voiceDraftStore, /localStorage/);
});

test("operator UI exposes exact voice, review, blocker, and delivery evidence", () => {
  assert.match(voiceRecorder, /approval_status/);
  assert.match(voiceRecorder, /referenced_by_timeline/);
  assert.match(voiceRecorder, /Использовать этот дубль/);
  assert.match(voiceRecorder, /asset_id/);
  assert.match(reviewWorkspace, /artifact_evidence/);
  assert.match(reviewWorkspace, /publication_evidence/);
  assert.match(reviewWorkspace, /active_audio_ratio_milli/);
  assert.match(workflowDashboard, /deliveryContext\.files/);
  assert.match(workflowDashboard, /item\.blob\.sha256/);
  assert.match(workflowDashboard, /deliveryContext\.candidate/);
  assert.match(app, /expected_candidate: expectedCandidate/);
  assert.match(workflowDashboard, /audio\.voice\.required/);
  assert.match(workflowDashboard, /audio\.voice\.silent/);
  assert.match(workflowDashboard, /package\.cover\.required/);
  assert.match(deliveryContextHook, /studioV3\.GET\("\/api\/v3\/delivery\/context"\)/);
});
