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
const frameStrip = await readFile(
  new URL("../src/review/FrameStrip.tsx", import.meta.url),
  "utf8",
);
const ui = [
  app,
  workflowDashboard,
  reviewWorkspace,
  reviewPlayer,
  reviewTimeline,
  reviewNotes,
  frameStrip,
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
  assert.match(app, /status\.action === "review"/);
  assert.match(workflowDashboard, /status\.action === "deliver"/);
  assert.doesNotMatch(app, /const STAGES|function currentStage/);
  assert.ok(app.split(/\r?\n/).length <= 200, "app.tsx must stay understandable");
});

test("review surface captures exact frame, range, region and TimelineIR targets", () => {
  assert.match(reviewWorkspace, /end_frame_exclusive/);
  assert.match(reviewWorkspace, /target_ids: activeTargets/);
  assert.match(reviewWorkspace, /expected_artifact: context\.artifact/);
  assert.match(reviewWorkspace, /expected_timeline: context\.timeline/);
  assert.match(reviewWorkspace, /nsToFrameCeil\(item\.start_ns/);
  assert.doesNotMatch(reviewWorkspace, /\bnsToFrame\(/);
  assert.match(reviewWorkspace, /studioV3\.GET\("\/api\/v3\/review\/context"\)/);
  assert.doesNotMatch(reviewWorkspace, /selectionMode|rangeAnchor|rangeEdge/);
  assert.match(frameStrip, /onPointerDown={handlePointerDown}/);
  assert.match(frameStrip, /onPointerMove={handlePointerMove}/);
  assert.match(frameStrip, /setDragSelection/);
  assert.match(frameStrip, /role="slider"/);
  assert.match(frameStrip, /aria-pressed={selected}/);
  assert.match(reviewPlayer, /onPointerDown={startRegion}/);
  assert.doesNotMatch(reviewPlayer, /setDrawing|selectionMode/);
  assert.match(reviewPlayer, /event\.target !== event\.currentTarget/);
  assert.match(reviewPlayer, /aria-label="На один кадр назад"/);
  assert.match(reviewPlayer, /toggleMute/);
  assert.match(reviewPlayer, /toggleFullscreen/);
  assert.match(reviewTimeline, /Слои, переходы и звук/);
  assert.match(reviewTimeline, /activeTargets\.includes\(item\.item_id\)/);
  assert.doesNotMatch(reviewTimeline, /onToggleTarget/);
  assert.match(reviewNotes, /hasUnsavedNote/);
  assert.match(reviewNotes, /role="status"/);
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
