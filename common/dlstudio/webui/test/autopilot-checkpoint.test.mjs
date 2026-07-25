import assert from "node:assert/strict";
import test from "node:test";
import { Buffer } from "node:buffer";
import { resolve } from "node:path";
import { build } from "esbuild";

const hooksStub = `
export function useState(initial) {
  const h = globalThis.__checkpointHooks;
  const i = h.stateIndex++;
  if (!(i in h.states)) h.states[i] = typeof initial === "function" ? initial() : initial;
  return [h.states[i], value => {
    h.states[i] = typeof value === "function" ? value(h.states[i]) : value;
  }];
}
`;
const jsxStub = `
export const Fragment = Symbol.for("test.fragment");
export function jsx(type, props, key) { return { type, props: props || {}, key }; }
export const jsxs = jsx;
`;

async function loadComponent() {
  const result = await build({
    entryPoints: [resolve("src/components/AutopilotCheckpoint.tsx")],
    bundle: true,
    format: "esm",
    platform: "node",
    write: false,
    jsx: "automatic",
    jsxImportSource: "preact",
    plugins: [{
      name: "checkpoint-test-stubs",
      setup(esbuild) {
        esbuild.onResolve({ filter: /^preact\/hooks$/ }, () => ({ path: "hooks", namespace: "stub" }));
        esbuild.onResolve({ filter: /^preact\/jsx-runtime$/ }, () => ({ path: "jsx", namespace: "stub" }));
        esbuild.onLoad({ filter: /^hooks$/, namespace: "stub" }, () => ({ contents: hooksStub, loader: "js" }));
        esbuild.onLoad({ filter: /^jsx$/, namespace: "stub" }, () => ({ contents: jsxStub, loader: "js" }));
      },
    }],
  });
  return import(`data:text/javascript;base64,${Buffer.from(result.outputFiles[0].text).toString("base64")}`);
}

function descendants(node) {
  if (node == null || typeof node === "boolean") return [];
  if (Array.isArray(node)) return node.flatMap(descendants);
  if (typeof node !== "object") return [];
  if (typeof node.type === "function") return descendants(node.type(node.props || {}));
  return [node, ...descendants(node.props?.children)];
}
function textOf(node) {
  if (node == null || typeof node === "boolean") return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(textOf).join("");
  if (typeof node.type === "function") return textOf(node.type(node.props || {}));
  return textOf(node.props?.children);
}

test("checkpoint renders the consolidated decision table and all four actions", async () => {
  globalThis.__checkpointHooks = { states: [], stateIndex: 0 };
  const { AutopilotCheckpoint } = await loadComponent();
  const calls = [];
  const tree = AutopilotCheckpoint({
    checkpoint: {
      wall_time: { budget_minutes: 60, elapsed_minutes: 18, remaining_minutes: 42, stage: "checkpoint" },
      blockers: [], missing_inputs: [], can_approve_all: true, approved_all: false,
      rows: [{
        id: "b01_s01", vo_thesis: "Я начал игру заново", duration_seconds: 3.5,
        quality_flags: ["VQ-PACE"], proposed_fix: "Keep real footage", approved: false,
        shot: { src: "data/game.mp4", provenance: "game_capture", source_role: "real_product" },
      }],
    },
    busy: false,
    error: null,
    onApproveAll: async () => calls.push("approve_all"),
    onRequest: async (action, shotId) => calls.push(`${action}:${shotId}`),
  });

  const text = textOf(tree);
  assert.match(text, /18\.0 \/ 60\.0 min/);
  assert.match(text, /Я начал игру заново/);
  assert.match(text, /game_capture/);
  assert.match(text, /3\.50s/);
  for (const label of ["Approve all", "Replace shot", "Request capture", "Change text"]) {
    assert.ok(text.includes(label), `missing ${label}`);
  }
  const buttons = descendants(tree).filter((node) => node.type === "button");
  for (const button of buttons) await button.props.onClick();
  assert.deepEqual(calls, [
    "approve_all",
    "replace_shot:b01_s01",
    "request_capture:b01_s01",
    "change_text:b01_s01",
  ]);
});

test("checkpoint disables package approval while blockers exist", async () => {
  globalThis.__checkpointHooks = { states: [], stateIndex: 0 };
  const { AutopilotCheckpoint } = await loadComponent();
  const tree = AutopilotCheckpoint({
    checkpoint: {
      wall_time: { budget_minutes: 60, elapsed_minutes: 65, remaining_minutes: 0, stage: "checkpoint" },
      blockers: [{ severity: "error", code: "VQ-SOURCE", message: "capture missing", where: "b01_s01" }],
      missing_inputs: [], can_approve_all: false, approved_all: false, rows: [],
    },
    busy: false, error: null, onApproveAll: async () => {}, onRequest: async () => {},
  });
  const approve = descendants(tree).find((node) => node.type === "button" && textOf(node) === "Approve all");
  assert.equal(approve.props.disabled, true);
  assert.match(textOf(tree), /capture missing/);
});
