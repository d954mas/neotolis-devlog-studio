import assert from "node:assert/strict";
import test from "node:test";
import { Buffer } from "node:buffer";
import { resolve } from "node:path";
import { build } from "esbuild";

async function loadGate() {
  const result = await build({
    entryPoints: [resolve("src/lib/latestRequest.ts")],
    bundle: true,
    format: "esm",
    platform: "node",
    write: false,
  });
  const code = result.outputFiles[0].text;
  return import(
    `data:text/javascript;base64,${Buffer.from(code).toString("base64")}`
  );
}

test("latest request gate rejects stale filters and stale pagination", async () => {
  const { LatestRequestGate } = await loadGate();
  const gate = new LatestRequestGate();

  const first = gate.begin("project-a|30d|newest", false);
  const second = gate.begin("project-a|7d|views", false);
  assert.equal(gate.isCurrent(first, "project-a|30d|newest"), false);
  assert.equal(gate.isCurrent(second, "project-a|7d|views"), true);
  assert.equal(gate.begin("project-a|30d|newest", true), null);

  const page = gate.begin("project-a|7d|views", true);
  assert.equal(gate.isCurrent(page, "project-a|7d|views"), true);
  gate.invalidate("project-b|7d|views");
  assert.equal(gate.isCurrent(page, "project-a|7d|views"), false);
});
