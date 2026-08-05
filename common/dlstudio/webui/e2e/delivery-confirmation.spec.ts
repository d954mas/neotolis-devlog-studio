import { expect, test } from "@playwright/test";
import { baseURL } from "./helpers";

test("delivery confirms the exact visible candidate and stays usable at narrow width", async ({ page }) => {
  const candidate = { sha256: "c".repeat(64), size: 2048 };
  await page.route("**/api/v3/status", (route) => route.fulfill({
    status: 200,
    json: {
      action: "deliver",
      completed: false,
      current_stage: "deliver",
      production_id: "fixture.delivery",
      stage_order: ["prepare", "draft", "final", "review", "package", "deliver"],
      workflow: {
        attempts: [],
        delivery_receipt: null,
        eligible_candidate: candidate,
        kind: "reel",
        production_id: "fixture.delivery",
        revision: 12,
        run_id: "run.delivery",
      },
    },
  }));
  await page.route("**/api/v3/delivery/context", (route) => route.fulfill({
    status: 200,
    json: {
      candidate,
      candidate_id: candidate.sha256,
      files: [
        { path: "video.mp4", blob: { sha256: "a".repeat(64), size: 12345 } },
        { path: "youtube/metadata.md", blob: { sha256: "b".repeat(64), size: 321 } },
      ],
    },
  }));
  let submitted: unknown = null;
  await page.route("**/api/v3/deliver", async (route) => {
    submitted = route.request().postDataJSON();
    await route.fulfill({ status: 409, json: { detail: "eligible release candidate changed before delivery" } });
  });
  await page.setViewportSize({ width: 360, height: 760 });
  await page.goto(baseURL("exact"));

  await expect(page.getByText("video.mp4", { exact: true })).toBeVisible();
  await expect(page.getByText("youtube/metadata.md", { exact: true })).toBeVisible();
  await expect(page.getByText(/12.*345 bytes/)).toBeVisible();
  await page.getByRole("button", { name: "Deliver frozen candidate" }).click();
  await expect(page.getByRole("alert")).toContainText("candidate changed");
  expect(submitted).toEqual({
    destination_id: "local.delivery",
    expected_candidate: candidate,
  });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});
