import { expect, test } from "@playwright/test";
import { baseURL } from "./helpers";

const voiceContext = {
  production_id: "fixture.voice",
  script_text: "Знаете проблему вагонетки?",
  script_ref: { sha256: "a".repeat(64), size: 42 },
  state_revision: 7,
  takes: [],
};

test("a failed upload restores the unsaved voice take after reload", async ({
  page,
}) => {
  await page.route("**/api/v3/voice", async (route) => {
    await route.fulfill({ status: 200, json: voiceContext });
  });
  await page.goto(`${baseURL("exact")}/#voice`);
  await expect(page.getByRole("heading", { name: voiceContext.production_id })).toBeVisible();
  await page.waitForTimeout(1_000);

  await page.evaluate(async (identity) => {
    await new Promise<void>((resolve, reject) => {
      const request = indexedDB.open("dlstudio-voice", 1);
      request.onerror = () => reject(request.error);
      request.onblocked = () => reject(new Error("voice database open blocked"));
      request.onsuccess = () => {
        const database = request.result;
        const transaction = database.transaction("drafts", "readwrite");
        transaction.objectStore("drafts").put(
          {
            blob: new Blob(["voice-draft"], { type: "audio/webm" }),
            elapsedMs: 2_400,
            recordedAt: "2026-08-04T12:00:00.000Z",
            productionId: identity.production_id,
            scriptRef: identity.script_ref,
          },
          `${identity.production_id}:${identity.script_ref.sha256}:${identity.script_ref.size}`,
        );
        transaction.oncomplete = () => {
          database.close();
          resolve();
        };
        transaction.onerror = () => reject(transaction.error);
      };
    });
  }, voiceContext);
  await page.route("**/api/v3/voice/takes?**", async (route) => {
    expect(route.request().headers()["x-production-id"]).toBe(voiceContext.production_id);
    expect(route.request().headers()["x-script-sha256"]).toBe(voiceContext.script_ref.sha256);
    await route.fulfill({
      status: 409,
      json: { detail: "temporary ingest failure" },
    });
  });

  await page.reload();
  await expect(page.getByText("ВОССТАНОВЛЕННЫЙ ЧЕРНОВИК")).toBeVisible();
  await expect(page.getByText("00:02").first()).toBeVisible();
  await page.getByRole("button", { name: "Сохранить дубль" }).click();
  await expect(page.getByRole("alert")).toContainText("temporary ingest failure");

  await page.reload();
  await expect(page.getByText("ВОССТАНОВЛЕННЫЙ ЧЕРНОВИК")).toBeVisible();
  await expect(page.getByRole("button", { name: "Сохранить дубль" })).toBeVisible();
});

test("a draft from another exact script is not restored", async ({ page }) => {
  await page.route("**/api/v3/voice", (route) => route.fulfill({ status: 200, json: voiceContext }));
  await page.goto(`${baseURL("exact")}/#voice`);
  await page.waitForTimeout(1_000);
  await page.evaluate(async () => {
    await new Promise<void>((resolve, reject) => {
      const request = indexedDB.open("dlstudio-voice", 1);
      request.onerror = () => reject(request.error);
      request.onblocked = () => reject(new Error("voice database open blocked"));
      request.onsuccess = () => {
        const database = request.result;
        const transaction = database.transaction("drafts", "readwrite");
        const oldRef = { sha256: "b".repeat(64), size: 41 };
        transaction.objectStore("drafts").put(
          {
            blob: new Blob(["old-script-draft"], { type: "audio/webm" }),
            elapsedMs: 1_200,
            recordedAt: "2026-08-04T12:00:00.000Z",
            productionId: "fixture.voice",
            scriptRef: oldRef,
          },
          `fixture.voice:${oldRef.sha256}:${oldRef.size}`,
        );
        transaction.oncomplete = () => { database.close(); resolve(); };
        transaction.onerror = () => reject(transaction.error);
      };
    });
  });
  await page.reload();

  await expect(page.getByText("ВОССТАНОВЛЕННЫЙ ЧЕРНОВИК")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Сохранить дубль" })).toHaveCount(0);
});

test("voice take statuses are exhaustive and rejected takes cannot be approved", async ({ page }) => {
  const take = (status: string, index: number, reason: string | null = null) => ({
    approval_status: status,
    approval_reason: reason,
    asset_id: `voice.take.${index}`,
    blob: { sha256: String(index).repeat(64), size: 10 },
    codec: "opus",
    current_script: true,
    duration_ns: 1_000_000_000,
    format_name: "webm",
    mime_type: "audio/webm",
    recorded_at: "2026-08-04T12:00:00.000Z",
    referenced_by_timeline: index === 3,
    take_id: `take${index}`,
  });
  await page.route("**/api/v3/voice", (route) => route.fulfill({
    status: 200,
    json: {
      ...voiceContext,
      takes: [
        take("pending", 1),
        take("validated", 2),
        take("approved", 3),
        take("rejected", 4, "wrong reading"),
      ],
    },
  }));
  await page.goto(`${baseURL("exact")}/#voice`);

  await expect(page.getByText("Ожидает проверки")).toBeVisible();
  await expect(page.getByText("Проверен, ожидает одобрения")).toBeVisible();
  await expect(page.getByText("Одобрен", { exact: true })).toBeVisible();
  await expect(page.getByText("Отклонён: wrong reading")).toBeVisible();
  await expect(page.getByRole("button", { name: "Использовать этот дубль" })).toHaveCount(2);
  await expect(page.getByText("В текущем TimelineIR")).toBeVisible();
});
