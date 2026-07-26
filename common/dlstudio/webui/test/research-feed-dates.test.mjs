import assert from "node:assert/strict";
import test from "node:test";
import { Buffer } from "node:buffer";
import { resolve } from "node:path";
import { build } from "esbuild";

async function loadDateHelpers() {
  const result = await build({
    entryPoints: [resolve("src/components/research/research-feed-dates.ts")],
    bundle: true,
    format: "esm",
    platform: "node",
    write: false,
  });
  return import(`data:text/javascript;base64,${Buffer.from(result.outputFiles[0].text).toString("base64")}`);
}

test("historical feed groups already-sorted Reels by displayed local calendar day", async () => {
  const { groupReelsByDate } = await loadDateHelpers();
  const reels = [
    { id: "newest", published_at: "2026-07-19T18:00:00" },
    { id: "same-day", published_at: "2026-07-19T08:00:00" },
    { id: "older", published_at: "2026-07-18T23:00:00" },
  ];

  const groups = groupReelsByDate(reels);
  assert.deepEqual(groups.map((group) => group.date), ["2026-07-19", "2026-07-18"]);
  assert.deepEqual(groups[0].reels.map((reel) => reel.id), ["newest", "same-day"]);
  assert.deepEqual(groups[1].reels.map((reel) => reel.id), ["older"]);
});

test("date headers use the same Today and weekday buckets as Diary", async () => {
  const { dateGroupLabel } = await loadDateHelpers();
  const now = new Date(2026, 6, 19, 20, 0, 0);

  assert.equal(dateGroupLabel("2026-07-19T08:00:00", now), "Today");
  assert.equal(dateGroupLabel("2026-07-18T08:00:00", now), "Yesterday");
  assert.match(dateGroupLabel("2026-07-13T08:00:00", now), /^Mon, Jul 13$/);
});
