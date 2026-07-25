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
    entryPoints: [resolve("src/components/ProductOverview.tsx")],
    bundle: true,
    format: "esm",
    platform: "node",
    write: false,
    jsx: "automatic",
    jsxImportSource: "preact",
    plugins: [{
      name: "product-overview-test-stubs",
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
  if (typeof node.type === "function") return textOf(node.type(node.props || {}));
  return textOf(node.props?.children);
}

test("product overview shows devlog and reel on the same Studio page", async () => {
  const { ProductOverview } = await loadComponent();
  const tree = ProductOverview({
    product: {
      id: "not_a_trolley_problem",
      title: "Not a Trolley Problem",
      current_production_id: "2026_07_18_reel_01",
      productions: [
        { id: "2026_07_17_devlog_01", kind: "devlog", date: "2026-07-17", orientation: "landscape", studio_ref: "not_a_trolley_problem:2026_07_17_devlog_01", current: false },
        { id: "2026_07_18_reel_01", kind: "reel", date: "2026-07-18", orientation: "vertical", studio_ref: "not_a_trolley_problem:2026_07_18_reel_01", current: true },
      ],
    },
  });
  const text = textOf(tree);
  assert.match(text, /Not a Trolley Problem/);
  assert.match(text, /DEVLOG/);
  assert.match(text, /REEL/);
  assert.match(text, /2026_07_17/);
  assert.match(text, /2026_07_18/);
  assert.match(text, /open/);
});
