import assert from "node:assert/strict";
import test from "node:test";
import { Buffer } from "node:buffer";
import { resolve } from "node:path";
import { build } from "esbuild";

const hooksStub = `
export function useState(initial) {
  const h = globalThis.__recordTabHooks;
  const i = h.stateIndex++;
  if (!(i in h.states)) h.states[i] = typeof initial === "function" ? initial() : initial;
  return [h.states[i], value => {
    h.states[i] = typeof value === "function" ? value(h.states[i]) : value;
  }];
}
export function useRef(initial) {
  const h = globalThis.__recordTabHooks;
  const i = h.refIndex++;
  if (!(i in h.refs)) h.refs[i] = { current: initial };
  return h.refs[i];
}
export function useEffect() {}
`;

const jsxStub = `
export const Fragment = Symbol.for("test.fragment");
export function jsx(type, props, key) { return { type, props: props || {}, key }; }
export const jsxs = jsx;
`;

const recorderStub = `
export class MicRecorder {
  ready = true;
  recording = false;
  mimeType = "audio/webm";
  onMeter = null;
  beginTake() { this.recording = true; }
  async stopTake() { this.recording = false; return new Blob([]); }
  async open() {}
  close() {}
}
export function fileExtForMime() { return "webm"; }
`;

async function loadRecordTab() {
  const result = await build({
    entryPoints: [resolve("src/components/RecordTab.tsx")],
    bundle: true,
    format: "esm",
    platform: "node",
    write: false,
    jsx: "automatic",
    jsxImportSource: "preact",
    plugins: [
      {
        name: "record-tab-test-stubs",
        setup(esbuild) {
          esbuild.onResolve({ filter: /^preact\/hooks$/ }, () => ({
            path: "hooks",
            namespace: "test-stub",
          }));
          esbuild.onResolve({ filter: /^preact\/jsx-runtime$/ }, () => ({
            path: "jsx-runtime",
            namespace: "test-stub",
          }));
          esbuild.onResolve({ filter: /^\.\.\/lib\/recorder$/ }, () => ({
            path: "recorder",
            namespace: "test-stub",
          }));
          esbuild.onLoad({ filter: /^hooks$/, namespace: "test-stub" }, () => ({
            contents: hooksStub,
            loader: "js",
          }));
          esbuild.onLoad(
            { filter: /^jsx-runtime$/, namespace: "test-stub" },
            () => ({ contents: jsxStub, loader: "js" }),
          );
          esbuild.onLoad(
            { filter: /^recorder$/, namespace: "test-stub" },
            () => ({ contents: recorderStub, loader: "js" }),
          );
        },
      },
    ],
  });
  const code = result.outputFiles[0].text;
  return import(`data:text/javascript;base64,${Buffer.from(code).toString("base64")}`);
}

function render(RecordTab, props) {
  globalThis.__recordTabHooks.stateIndex = 0;
  globalThis.__recordTabHooks.refIndex = 0;
  return RecordTab(props);
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

test("recording keeps the full VO visible and advances a live karaoke fragment", async () => {
  globalThis.__recordTabHooks = { states: [], refs: [], stateIndex: 0, refIndex: 0 };
  let now = 1_000;
  let timerTick = null;
  let postRollTick = null;
  let addedTake = null;
  const realDateNow = Date.now;
  Date.now = () => now;
  globalThis.window = {
    setInterval(callback) {
      timerTick = callback;
      return 1;
    },
    clearInterval() {},
    setTimeout(callback) {
      postRollTick = callback;
      return 2;
    },
    clearTimeout() {},
  };

  try {
    const { RecordTab } = await loadRecordTab();
    const vo =
      "Первый фрагмент нужно читать спокойно и без спешки. " +
      "Второй фрагмент должен появиться позже во время записи. " +
      "Третий фрагмент завершает карточку и остаётся видимым целиком.";
    const props = {
      beat: {
        id: "b01",
        title: "Hook",
        vo,
        stage: null,
        face: "none",
        duration: null,
        n_chunks: 0,
        audio: null,
        words: null,
        rendered: false,
      },
      takes: [],
      addTake(take) { addedTake = take; },
      updateTake() {},
      onAfterProcess() {},
    };

    let tree = render(RecordTab, props);
    const recordButton = descendants(tree).find(
      (node) => node.props?.class?.split(" ").includes("record") && node.props?.onClick,
    );
    assert.ok(recordButton, "Record button must be rendered");
    await recordButton.props.onClick();

    tree = render(RecordTab, props);
    assert.ok(textOf(tree).includes(vo), "the entire current beat VO must stay visible");
    const firstLive = descendants(tree).find(
      (node) => node.props?.["aria-live"] === "polite",
    );
    assert.ok(
      firstLive,
      "recording mode must expose the current karaoke/progress fragment with aria-live",
    );
    const firstFragment = textOf(firstLive).trim();
    assert.equal(
      firstFragment,
      "3",
      "the media stream must already be recording during a three-second room-tone lead-in",
    );

    now += 2_000;
    assert.ok(timerTick, "recording must start the progress timer");
    timerTick();
    tree = render(RecordTab, props);
    const countdownLive = descendants(tree).find(
      (node) => node.props?.["aria-live"] === "polite",
    );
    assert.equal(textOf(countdownLive).trim(), "1", "countdown must advance before speech");

    now += 2_000;
    timerTick();
    tree = render(RecordTab, props);
    const roomToneLive = descendants(tree).find(
      (node) => node.props?.["aria-live"] === "polite",
    );
    assert.equal(
      textOf(roomToneLive).trim(),
      "Тишина",
      "a separate two-second room-tone phase must follow the countdown",
    );

    now += 5_000;
    timerTick();
    tree = render(RecordTab, props);
    const nextLive = descendants(tree).find(
      (node) => node.props?.["aria-live"] === "polite",
    );
    assert.notEqual(
      textOf(nextLive).trim(),
      firstFragment,
      "the spoken/progress fragment must advance while recording",
    );

    const stopButton = descendants(tree).find(
      (node) => node.props?.class?.split(" ").includes("record") && node.props?.onClick,
    );
    await stopButton.props.onClick();
    tree = render(RecordTab, props);
    assert.ok(
      textOf(tree).includes("Saving post-roll"),
      "stop must enter an automatic post-roll instead of stopping immediately",
    );
    assert.ok(postRollTick, "post-roll completion must be scheduled");
    postRollTick();
    await Promise.resolve();
    await Promise.resolve();
    assert.equal(addedTake?.recordingMetadata?.speech_start_seconds, 5);
    assert.equal(addedTake?.recordingMetadata?.post_roll_target_seconds, 1);
    assert.equal(addedTake?.recordingMetadata?.post_roll_completed, true);
  } finally {
    Date.now = realDateNow;
    delete globalThis.window;
    delete globalThis.__recordTabHooks;
  }
});

test("take card shows a clear re-record reason from machine QC", async () => {
  globalThis.__recordTabHooks = { states: [], refs: [], stateIndex: 0, refIndex: 0 };
  globalThis.window = {
    setInterval() { return 1; },
    clearInterval() {},
    setTimeout() { return 2; },
    clearTimeout() {},
  };
  try {
    const { RecordTab } = await loadRecordTab();
    const tree = render(RecordTab, {
      beat: {
        id: "b01",
        title: "Hook",
        vo: "Voice over",
        stage: null,
        face: "none",
        duration: null,
        n_chunks: 0,
        audio: null,
        words: null,
        rendered: false,
      },
      takes: [{
        id: "take-1",
        beatId: "b01",
        filename: "take.webm",
        url: "blob:take",
        size: 128,
        createdAt: 1,
        uploadState: "uploaded",
        processState: "error",
        qualityStatus: "re_record",
        qualityMessage: "Click, clipping, or incomplete clean handles detected",
      }],
      addTake() {},
      updateTake() {},
      onAfterProcess() {},
    });

    assert.ok(textOf(tree).includes("Re-record"));
    assert.ok(textOf(tree).includes("Click, clipping, or incomplete clean handles detected"));
  } finally {
    delete globalThis.window;
    delete globalThis.__recordTabHooks;
  }
});
