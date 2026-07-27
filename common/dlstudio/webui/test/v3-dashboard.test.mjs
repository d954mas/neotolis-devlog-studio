import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
import test from "node:test";

const app = await readFile(new URL("../src/app.tsx", import.meta.url), "utf8");
const http = await readFile(
  new URL("../../src/dlstudio/adapters/http.py", import.meta.url),
  "utf8",
);

test("dashboard uses only the generated Studio v3 client surface", () => {
  assert.match(app, /from "\.\/api\/v3\.client"/);
  assert.match(app, /studioV3\.GET\("\/api\/v3\/status"\)/);
  for (const path of ["advance", "review", "deliver"]) {
    assert.match(app, new RegExp(`studioV3\\.POST\\("\\/api\\/v3\\/${path}"`));
  }
  for (const banned of ["/api/file", "pollJob", "job_id", "/api/project", "/research/"]) {
    assert.doesNotMatch(app, new RegExp(banned));
  }
});

test("review and delivery controls are stage-gated", () => {
  assert.match(app, />Start production<\/button>/);
  assert.match(app, /status\.action === "advance"/);
  assert.match(app, /status\.action === "review"/);
  assert.match(app, /status\.action === "deliver"/);
  assert.doesNotMatch(app, /const STAGES|function currentStage/);
  assert.ok(app.split(/\r?\n/).length <= 200, "app.tsx must stay understandable");
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
