import assert from "node:assert/strict";
import test from "node:test";
import { resolve } from "node:path";
import { build } from "esbuild";

async function loadTakesModule() {
  const result = await build({
    entryPoints: [resolve("src/lib/takes.ts")],
    bundle: true,
    format: "esm",
    platform: "node",
    write: false,
  });
  return import(
    `data:text/javascript;base64,${Buffer.from(result.outputFiles[0].text).toString("base64")}`
  );
}

test("uploaded takes and processing job ids survive serialization", async () => {
  const { restoreUploadedTakes, serializeUploadedTakes } = await loadTakesModule();
  const raw = serializeUploadedTakes({
    hook: [
      {
        id: "take-1",
        beatId: "hook",
        filename: "hook.webm",
        url: "blob:temporary",
        size: 123,
        createdAt: 42,
        uploadState: "uploaded",
        serverPath: "data/recordings/hook.webm",
        processState: "running",
        processJobId: "job-123",
      },
      {
        id: "take-local",
        beatId: "hook",
        filename: "local.webm",
        url: "blob:local",
        size: 1,
        createdAt: 43,
        uploadState: "uploading",
        processState: "idle",
      },
    ],
  });

  const restored = restoreUploadedTakes(raw, (path) => `/api/file?path=${path}`);
  assert.equal(restored.hook.length, 1);
  assert.equal(restored.hook[0].processJobId, "job-123");
  assert.equal(restored.hook[0].processState, "idle");
  assert.match(restored.hook[0].processMessage, /resume status/);
  assert.equal(restored.hook[0].url, "/api/file?path=data/recordings/hook.webm");
});

test("invalid or cross-beat persisted entries are rejected", async () => {
  const { restoreUploadedTakes } = await loadTakesModule();
  const raw = JSON.stringify({
    version: 1,
    takes: {
      hook: [{
        id: "take-1",
        beatId: "other",
        filename: "hook.webm",
        serverPath: "data/recordings/hook.webm",
      }],
    },
  });
  assert.deepEqual(restoreUploadedTakes(raw, String), {});
});
