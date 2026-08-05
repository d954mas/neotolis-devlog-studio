import { expect, test } from "@playwright/test";
import { baseURL } from "./helpers";

test("saving a restored draft focuses exact canonical evidence", async ({ page }) => {
  const scriptRef = { sha256: "d".repeat(64), size: 37 };
  const context = {
    production_id: "fixture.voice-save",
    script_text: "Save this exact recording.",
    script_ref: scriptRef,
    state_revision: 4,
    takes: [],
  };
  await page.route("**/api/v3/voice", (route) => route.fulfill({
    status: 200,
    json: context,
  }));
  await page.goto(`${baseURL("exact")}/#voice`);
  await page.waitForTimeout(1_000);
  await page.evaluate(async (identity) => {
    await new Promise<void>((resolve, reject) => {
      const request = indexedDB.open("dlstudio-voice", 1);
      request.onerror = () => reject(request.error);
      request.onsuccess = () => {
        const database = request.result;
        const transaction = database.transaction("drafts", "readwrite");
        transaction.objectStore("drafts").put(
          {
            blob: new Blob(["voice-draft"], { type: "audio/webm" }),
            elapsedMs: 1_250,
            recordedAt: "2026-08-04T12:00:00.000Z",
            productionId: identity.production_id,
            scriptRef: identity.script_ref,
          },
          `${identity.production_id}:${identity.script_ref.sha256}:${identity.script_ref.size}`,
        );
        transaction.oncomplete = () => { database.close(); resolve(); };
        transaction.onerror = () => reject(transaction.error);
      };
    });
  }, context);
  const savedTake = {
    approval_status: "pending",
    approval_reason: null,
    asset_id: "voice.take.saved",
    blob: { sha256: "e".repeat(64), size: 11 },
    codec: "opus",
    current_script: true,
    duration_ns: 1_250_000_000,
    format_name: "webm",
    mime_type: "audio/webm",
    recorded_at: "2026-08-04T12:00:00.000Z",
    referenced_by_timeline: false,
    take_id: "saved",
  };
  await page.route("**/api/v3/voice/takes?**", (route) => route.fulfill({
    status: 200,
    json: { ...context, state_revision: 5, takes: [savedTake] },
  }));

  await page.reload();
  await page.locator("button.save-action").click();

  const confirmation = page.locator(".voice-confirmation");
  await expect(confirmation).toContainText("Saved take saved");
  await expect(confirmation).toContainText("state revision 5");
  await expect(confirmation).toContainText("current script");
  await expect(confirmation).toContainText("00:01");
  await expect(confirmation).toContainText("pending");
  await expect(confirmation).toBeFocused();
});
