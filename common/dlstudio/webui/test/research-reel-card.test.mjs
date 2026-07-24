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

const hooksStub = `
export function useState(value) { return [value, () => {}]; }
`;

async function loadComponent() {
  const result = await build({
    entryPoints: [resolve("src/components/research/ReelCard.tsx")],
    bundle: true,
    format: "esm",
    platform: "node",
    write: false,
    jsx: "automatic",
    jsxImportSource: "preact",
    plugins: [{
      name: "research-card-test-stubs",
      setup(esbuild) {
        esbuild.onResolve({ filter: /^preact\/jsx-runtime$/ }, () => ({ path: "jsx", namespace: "stub" }));
        esbuild.onResolve({ filter: /^preact\/hooks$/ }, () => ({ path: "hooks", namespace: "stub" }));
        esbuild.onLoad({ filter: /^jsx$/, namespace: "stub" }, () => ({ contents: jsxStub, loader: "js" }));
        esbuild.onLoad({ filter: /^hooks$/, namespace: "stub" }, () => ({ contents: hooksStub, loader: "js" }));
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

function findByClass(node, className) {
  if (node == null || typeof node !== "object") return null;
  if (Array.isArray(node)) {
    for (const child of node) {
      const found = findByClass(child, className);
      if (found) return found;
    }
    return null;
  }
  if (typeof node.type === "function") return findByClass(node.type(node.props || {}), className);
  if (String(node.props?.class ?? "").split(/\s+/).includes(className)) return node;
  return findByClass(node.props?.children, className);
}

test("research card makes adaptation and agent context explicit", async () => {
  const { ReelCard } = await loadComponent();
  const tree = ReelCard({
    projectId: "gamedev",
    reel: {
      id: "reference-1",
      author_id: "creator-1",
      platform: "instagram",
      url: "https://www.instagram.com/reel/example/",
      caption: "",
      thumbnail_url: "",
      published_at: "2026-07-18T12:00:00Z",
      duration_seconds: 21,
      views: 120000,
      likes: 9000,
      comments: 220,
      metrics_captured_at: "2026-07-19T12:00:00Z",
      metrics_history: [{ captured_at: "2026-07-19T12:00:00Z", views: 120000, likes: 9000, comments: 220 }],
      hook: "I broke the level in the first second",
      patterns: ["failure first", "fast reveal"],
      author: {
        id: "creator-1",
        username: "topdev",
        display_name: "Top Dev",
        profile_url: "",
        followers_count: 50000,
        median_views: 30000,
      },
      age_hours: 24,
      metrics_age_hours: 0,
      views_per_hour: 5000,
      growth_views: null,
      growth_hours: null,
      growth_per_hour: null,
      velocity: 5000,
      outlier_score: 4,
      experiment: {
        id: "experiment-1",
        reel_id: "reference-1",
        mode: "adaptation",
        status: "idea",
        hypothesis: "A failure-first opening will make our mechanic understandable.",
        take_from_reference: ["failure first"],
        keep_original: ["our footage", "our voice"],
        created_at: "2026-07-19T12:00:00Z",
        agent_context_path: "data/research/projects/gamedev/experiments/experiment-1.md",
        result: null,
      },
    },
    experimentBusy: false,
    onAuthor() {},
    async onExperiment() { return true; },
    async onExperimentResult() { return true; },
    onCacheChange() {},
  });

  assert.match(tree.props.class, /mode-adaptation/);
  const text = textOf(tree);
  assert.match(text, /Adaptation/);
  assert.match(text, /failure-first opening/);
  assert.match(text, /experiments\/experiment-1\.md/);
  assert.match(text, /4×/);
  assert.match(text, /updated <1h ago/);
  assert.match(text, /Record our result/);
  assert.match(text, /Скачать и смотреть/);
});

test("research card turns a long caption into a scannable headline", async () => {
  const { ReelCard } = await loadComponent();
  const tree = ReelCard({
    projectId: "gamedev",
    reel: {
      id: "reference-2",
      author_id: "creator-2",
      url: "https://www.instagram.com/reel/example-2/",
      caption: "Would you play for 400 real days? The world changes while you are away. https://example.com #gamedev #steam",
      thumbnail_url: "",
      published_at: "2026-07-18T12:00:00Z",
      duration_seconds: 30,
      views: 650000,
      likes: 17000,
      metrics_age_hours: 0,
      hook: "",
      patterns: [],
      author: { username: "gamepitch" },
      velocity: 4400,
      outlier_score: 32.1,
      growth_views: null,
      experiment: null,
    },
    experimentBusy: false,
    onAuthor() {},
    async onExperiment() { return true; },
    async onExperimentResult() { return true; },
    onCacheChange() {},
  });

  const title = findByClass(tree, "reel-title");
  assert.equal(textOf(title), "Would you play for 400 real days?");
  assert.equal(textOf(findByClass(tree, "reel-notes")), "The world changes while you are away.");
  assert.doesNotMatch(textOf(tree), /#gamedev|https:\/\//);
  assert.equal(findByClass(tree, "reel-visual").props["aria-label"], "Open Reel by @gamepitch");
  assert.equal(findByClass(tree, "reel-metric-overlay").props["aria-label"], "Reel performance");
});
