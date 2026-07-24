import assert from "node:assert/strict";
import test from "node:test";
import { Buffer } from "node:buffer";
import { resolve } from "node:path";
import { build } from "esbuild";

const jsxStub = `
export const Fragment = Symbol.for("test.fragment");
export function jsx(type, props, key) { return { type, props: props || {}, key }; }
export const jsxs = jsx;
`;

async function loadComponent() {
  const result = await build({
    entryPoints: [resolve("src/components/research/ResearchToolbar.tsx")],
    bundle: true,
    format: "esm",
    platform: "node",
    write: false,
    jsx: "automatic",
    jsxImportSource: "preact",
    plugins: [{
      name: "research-toolbar-test-stubs",
      setup(esbuild) {
        esbuild.onResolve({ filter: /^preact\/jsx-runtime$/ }, () => ({ path: "jsx", namespace: "stub" }));
        esbuild.onLoad({ filter: /^jsx$/, namespace: "stub" }, () => ({ contents: jsxStub, loader: "js" }));
      },
    }],
  });
  return import(`data:text/javascript;base64,${Buffer.from(result.outputFiles[0].text).toString("base64")}`);
}

function textOf(node) {
  if (node == null || typeof node === "boolean") return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(textOf).join(" ");
  return textOf(node.props?.children);
}

function countClass(node, className) {
  if (node == null || typeof node !== "object") return 0;
  if (Array.isArray(node)) return node.reduce((sum, child) => sum + countClass(child, className), 0);
  const own = String(node.props?.class ?? "").split(/\s+/).includes(className) ? 1 : 0;
  return own + countClass(node.props?.children, className);
}

const baseProps = {
  projects: [{ id: "gamedev", title: "Gamedev", author_count: 10, reel_count: 100, experiment_count: 0 }],
  activeId: "gamedev",
  feed: { id: "gamedev", title: "Gamedev" },
  range: "all",
  sort: "newest",
  busy: false,
  collectorConfigured: true,
  syncLabel: "Sync 10 authors",
  syncDisabled: false,
  addPanel: "ADD PANEL",
  toolsPanel: "TOOLS PANEL",
  onProject() {},
  onRange() {},
  onSort() {},
  onSync() {},
  onPanel() {},
};

test("research toolbar keeps secondary workflows closed by default", async () => {
  const { ResearchToolbar } = await loadComponent();
  const tree = ResearchToolbar({ ...baseProps, panel: null });

  assert.match(textOf(tree), /Pattern Lab/);
  assert.match(textOf(tree), /Sync 10 authors/);
  assert.equal(countClass(tree, "research-command-panel"), 0);
});

test("research toolbar exposes add workflow as an overlay panel", async () => {
  const { ResearchToolbar } = await loadComponent();
  const tree = ResearchToolbar({ ...baseProps, panel: "add" });

  assert.equal(countClass(tree, "research-command-panel"), 1);
  assert.match(textOf(tree), /ADD PANEL/);
  assert.doesNotMatch(textOf(tree), /TOOLS PANEL/);
});
