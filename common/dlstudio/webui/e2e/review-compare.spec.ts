import { expect, test } from "@playwright/test";
import {
  baseURL,
  expectNoHorizontalOverflow,
  openReview,
} from "./helpers";

test("maps and clamps different frame clocks while old video keeps playback and audio controls", async ({
  page,
}) => {
  await openReview(page, "compare");
  await expect(
    page.locator(".player-readout strong"),
  ).toHaveText("Кадр 29");
  await expect(page.locator(".time-range-readout")).toContainText(
    "Кадр 29",
  );

  await page.getByRole("button", { name: "До исправления" }).click();
  await expect(page.locator(".comparison-video")).toBeVisible();
  await expect(
    page.locator(".player-readout strong"),
  ).toHaveText("Кадр 44");
  const mediaFacts = await page.locator(".comparison-video").evaluate(
    async (video: HTMLVideoElement) => {
      if (video.readyState < HTMLMediaElement.HAVE_METADATA) {
        await new Promise<void>((resolve) => {
          video.addEventListener("loadedmetadata", () => resolve(), {
            once: true,
          });
        });
      }
      return {
        duration: video.duration,
        width: video.videoWidth,
        height: video.videoHeight,
      };
    },
  );
  expect(mediaFacts.duration).toBeGreaterThan(1.9);
  expect(mediaFacts.duration).toBeLessThan(2.1);
  expect(mediaFacts.width).toBe(180);
  expect(mediaFacts.height).toBe(320);

  await page
    .getByRole("button", { name: "На один кадр вперёд" })
    .click();
  await expect(
    page.locator(".player-readout strong"),
  ).toHaveText("Кадр 45");
  await page.getByRole("button", { name: "Выключить звук" }).click();
  await expect(
    page.getByRole("button", { name: "Включить звук" }),
  ).toBeVisible();
  expect(
    await page
      .locator(".comparison-video")
      .evaluate((video: HTMLVideoElement) => video.muted),
  ).toBe(true);
  await page.getByRole("slider", { name: "Громкость" }).fill("0.35");
  expect(
    await page
      .locator(".comparison-video")
      .evaluate((video: HTMLVideoElement) => video.volume),
  ).toBeCloseTo(0.35, 2);
  await page.getByRole("button", { name: "Смотреть" }).click();
  await expect
    .poll(() =>
      page
        .locator(".comparison-video")
        .evaluate((video: HTMLVideoElement) => video.currentTime),
    )
    .toBeGreaterThan(45 / 24);

  await expect(page.locator(".region-layer")).toHaveAttribute(
    "aria-disabled",
    "true",
  );
  await expect(
    page.getByRole("button", {
      name: "Отметить центральную область кадра",
    }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "Сейчас" }).click();
  await expect(page.locator(".comparison-video")).toHaveCount(0);
  await expect(
    page.locator(".player-readout strong"),
  ).toHaveText("Кадр 29");
});

test("same artifact uses one DOM media element and restores the current frame", async ({
  page,
}) => {
  const artifactURLs = new Set<string>();
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname.startsWith("/api/v3/review/artifacts/")) {
      artifactURLs.add(`${url.pathname}${url.search}`);
    }
  });
  await openReview(page, "same");
  await expect(page.getByText("Видео совпадает с прошлой версией.")).toBeVisible();
  await expect(
    page.locator(".player-readout strong"),
  ).toHaveText("Кадр 12");
  await expect(page.locator(".review-player video")).toHaveCount(1);
  await expect(page.locator(".comparison-video")).toHaveCount(0);

  await page.getByRole("button", { name: "До исправления" }).click();
  await expect(page.locator(".review-player video")).toHaveCount(1);
  await page
    .getByRole("button", { name: "На один кадр вперёд" })
    .click();
  await expect(
    page.locator(".player-readout strong"),
  ).toHaveText("Кадр 13");
  await page.getByRole("button", { name: "Сейчас" }).click();
  await expect(
    page.locator(".player-readout strong"),
  ).toHaveText("Кадр 12");
  await expect
    .poll(() =>
      page
        .locator(".current-video")
        .evaluate((video: HTMLVideoElement) => video.currentTime),
    )
    .toBeCloseTo(12 / 30, 2);
  expect(artifactURLs.size).toBe(1);
});

test("old-version keyboard control supports toggle, hold, and focus-loss cleanup", async ({
  page,
}) => {
  await openReview(page, "same");
  const oldButton = page.getByRole("button", { name: "До исправления" });

  await oldButton.press("Space");
  await expect(oldButton).toHaveAttribute("aria-pressed", "true");
  await oldButton.press("Space");
  await expect(oldButton).toHaveAttribute("aria-pressed", "false");

  await oldButton.focus();
  await page.keyboard.down("Space");
  await expect(oldButton).toHaveAttribute("aria-pressed", "true");
  await page.waitForTimeout(350);
  await page.keyboard.up("Space");
  await expect(oldButton).toHaveAttribute("aria-pressed", "false");

  await oldButton.focus();
  await page.keyboard.down("Space");
  await expect(oldButton).toHaveAttribute("aria-pressed", "true");
  await page.evaluate(() => window.dispatchEvent(new Event("blur")));
  await expect(oldButton).toHaveAttribute("aria-pressed", "false");
  await page.keyboard.up("Space");
});

test("review workspace has no document-level horizontal overflow at supported widths", async ({
  page,
}) => {
  const viewports = [
    { width: 1440, height: 900 },
    { width: 1024, height: 768 },
    { width: 390, height: 844 },
    { width: 320, height: 700 },
  ];
  await page.setViewportSize(viewports[0]);
  await openReview(page, "responsive");

  for (const viewport of viewports) {
    await page.setViewportSize(viewport);
    await expectNoHorizontalOverflow(page);
    await page.getByRole("button", { name: "До исправления" }).click();
    await expect(
      page.getByText("До · сравнение без разметки"),
    ).toBeVisible();
    await expectNoHorizontalOverflow(page);
    await page.getByRole("button", { name: "Сейчас" }).click();
  }

  await page.locator("details.technical-details").evaluate(
    (details: HTMLDetailsElement) => {
      details.open = true;
    },
  );
  await expectNoHorizontalOverflow(page);
  expect(page.url()).toBe(baseURL("responsive") + "/");
});
