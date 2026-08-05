import { expect, test } from "@playwright/test";
import { baseURL } from "./helpers";

test("approval preserves canonical errors and focuses exact success evidence", async ({ page }) => {
  const scriptRef = { sha256: "a".repeat(64), size: 42 };
  const pending = {
    approval_status: "pending",
    approval_reason: null,
    asset_id: "voice.take.5",
    blob: { sha256: "5".repeat(64), size: 10 },
    codec: "opus",
    current_script: true,
    duration_ns: 1_000_000_000,
    format_name: "webm",
    mime_type: "audio/webm",
    recorded_at: "2026-08-04T12:00:00.000Z",
    referenced_by_timeline: false,
    take_id: "take5",
  };
  const context = {
    production_id: "fixture.voice",
    script_text: "Exact current script.",
    script_ref: scriptRef,
    state_revision: 7,
    takes: [pending],
  };
  await page.route("**/api/v3/voice", (route) => route.fulfill({
    status: 200,
    json: context,
  }));
  let attempts = 0;
  await page.route("**/api/v3/voice/takes/*/approve", async (route) => {
    attempts += 1;
    const body = route.request().postDataJSON();
    expect(body.expected_production_id).toBe(context.production_id);
    expect(body.expected_script_ref).toEqual(scriptRef);
    if (attempts === 1) {
      await route.fulfill({
        status: 409,
        json: { detail: "voice approval belongs to another script" },
      });
      return;
    }
    await route.fulfill({
      status: 200,
      json: {
        ...context,
        state_revision: 8,
        takes: [{ ...pending, approval_status: "approved" }],
      },
    });
  });
  await page.goto(`${baseURL("exact")}/#voice`);

  await page.locator("button.use-take").click();
  await expect(page.getByRole("alert")).toContainText("another script");
  await page.locator("button.use-take").click();

  const confirmation = page.locator(".voice-confirmation");
  await expect(confirmation).toContainText("Approved take take5");
  await expect(confirmation).toContainText("state revision 8");
  await expect(confirmation).toContainText("current script");
  await expect(confirmation).toContainText("00:01");
  await expect(confirmation).toContainText("approved");
  await expect(confirmation).toBeFocused();
});
