import { expect, test } from "@playwright/test";
import {
  baseURL,
  expectNoHorizontalOverflow,
  openReview,
  reviewContext,
} from "./helpers";

test("maps exact clocks and lazily loads the old waveform without changing current selection", async ({
  page,
  request,
}) => {
  const context = await reviewContext(request, "compare");
  const packResponse = await request.get(
    `${baseURL("compare")}/api/v3/review/task-pack`,
  );
  expect(packResponse.ok()).toBeTruthy();
  const pack = await packResponse.json();
  const waveformRequests: string[] = [];
  page.on("request", (candidate) => {
    if (new URL(candidate.url()).pathname.endsWith("/waveform")) {
      waveformRequests.push(candidate.url());
    }
  });

  await openReview(page, "compare");
  await expect(
    page.locator(".review-time-track.current .waveform-shape"),
  ).toBeVisible();
  expect(
    waveformRequests.some((requestURL) => {
      const url = new URL(requestURL);
      return (
        url.pathname.includes(context.artifact.sha256) &&
        url.searchParams.get("size") === String(context.artifact.size) &&
        url.searchParams.get("samples") === "1024"
      );
    }),
  ).toBe(true);
  expect(
    waveformRequests.some((requestURL) =>
      new URL(requestURL).pathname.includes(pack.artifact.sha256),
    ),
  ).toBe(false);
  await expect(
    page.locator(".player-readout strong"),
  ).toHaveText("Кадр 29");
  await expect(page.locator(".time-range-readout")).toContainText(
    "Кадр 29",
  );
  const currentSlider = page.getByRole("slider", {
    name: /Сейчас · кадр или диапазон/,
  });
  await currentSlider.click({
    button: "right",
    position: { x: 2, y: 20 },
  });
  await page.keyboard.press("Escape");
  await expect(currentSlider).toHaveAttribute("aria-valuenow", "29");

  const oldWaveformRequest = page.waitForRequest((candidate) => {
    const url = new URL(candidate.url());
    return (
      url.pathname.endsWith(
        `/artifacts/${pack.artifact.sha256}/waveform`,
      ) &&
      url.searchParams.get("size") === String(pack.artifact.size) &&
      url.searchParams.get("samples") === "1024"
    );
  });
  await page.getByRole("button", { name: "До исправления" }).click();
  await oldWaveformRequest;
  await expect(
    page.locator(".review-time-track.previous .waveform-shape"),
  ).toBeVisible();
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
  const oldSlider = page.getByRole("slider", {
    name: /До · навигация/,
  });
  await oldSlider.press("Home");
  await expect(
    page.locator(".player-readout strong"),
  ).toHaveText("Кадр 0");
  await expect(oldSlider).toHaveAttribute(
    "aria-valuetext",
    /Кадр 0/,
  );
  const oldSelectionDescription =
    await oldSlider.getAttribute("aria-describedby");
  expect(oldSelectionDescription).not.toBeNull();
  await expect(
    page.locator(`#${oldSelectionDescription}`),
  ).toContainText("Исходное замечание");
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
    if (
      /^\/api\/v3\/review\/artifacts\/[0-9a-f]{64}$/.test(
        url.pathname,
      )
    ) {
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

test("leaving a loading old artifact cannot keep current review disabled", async ({
  page,
  request,
}) => {
  const packResponse = await request.get(
    `${baseURL("compare")}/api/v3/review/task-pack`,
  );
  expect(packResponse.ok()).toBeTruthy();
  const pack = await packResponse.json();
  let releaseOldMedia: (() => void) | undefined;
  const oldMediaGate = new Promise<void>((resolve) => {
    releaseOldMedia = resolve;
  });
  await page.route("**/api/v3/review/artifacts/*", async (route) => {
    const url = new URL(route.request().url());
    if (
      url.pathname.endsWith(`/artifacts/${pack.artifact.sha256}`)
    ) {
      await oldMediaGate;
    }
    await route.continue();
  });

  await openReview(page, "compare");
  const resolution = page
    .getByRole("button", { name: "Всё ещё не так" })
    .first();
  await expect(resolution).toBeEnabled();
  await page
    .getByRole("button", { name: "До исправления" })
    .click();
  await expect(page.locator(".comparison-video")).toBeVisible();
  await page.waitForTimeout(100);
  await page.getByRole("button", { name: "Сейчас" }).click();
  releaseOldMedia?.();

  await expect(page.locator(".comparison-video")).toHaveCount(0);
  await expect(resolution).toBeEnabled();
});

test("waveform failure and silent audio never block exact review navigation", async ({
  page,
  request,
}) => {
  await page.route("**/waveform*", async (route) => {
    await route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({ detail: "temporary waveform failure" }),
    });
  }, { times: 1 });
  await openReview(page, "responsive");
  const retry = page.getByRole("button", {
    name: "Повторить форму звука",
  });
  await expect(retry).toBeVisible();
  const retryBounds = await retry.boundingBox();
  expect(retryBounds?.height).toBeGreaterThanOrEqual(44);
  const slider = page.getByRole("slider", {
    name: /Сейчас · кадр или диапазон/,
  });
  await slider.press("Home");
  await expect(slider).toHaveAttribute("aria-valuenow", "0");
  await slider.press("ArrowRight");
  await expect(slider).toHaveAttribute("aria-valuenow", "1");
  await expect(
    page.getByRole("textbox", { name: "Комментарий" }),
  ).toBeEnabled();
  await retry.click();
  await expect(
    page.locator(".review-time-track.current .waveform-shape"),
  ).toBeVisible();

  const context = await reviewContext(request, "same");
  await page.route("**/waveform*", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        artifact: context.artifact,
        duration_ns: context.duration_ns,
        sample_count: 1024,
        has_audio: false,
        peaks_milli: Array.from({ length: 1024 }, () => 0),
      }),
    });
  });
  await openReview(page, "same");
  await expect(page.getByText("В этой версии нет звука")).toBeVisible();
  await expect(
    page.getByRole("slider", {
      name: /Сейчас · кадр или диапазон/,
    }),
  ).toBeEnabled();
});

test("waveform rejects a duration mismatch without exposing stale evidence", async ({
  page,
  request,
}) => {
  const context = await reviewContext(request, "responsive");
  let mismatch = true;
  await page.route("**/waveform*", async (route) => {
    if (!mismatch) {
      await route.continue();
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        artifact: context.artifact,
        duration_ns: context.duration_ns + 1,
        sample_count: 1024,
        has_audio: true,
        peaks_milli: Array.from({ length: 1024 }, () => 500),
      }),
    });
  });

  await openReview(page, "responsive");
  const retry = page.getByRole("button", {
    name: "Повторить форму звука",
  });
  await expect(retry).toBeVisible();
  await expect(
    page.locator(".review-time-track.current .waveform-shape"),
  ).toHaveCount(0);
  mismatch = false;
  await retry.click();
  await expect(
    page.locator(".review-time-track.current .waveform-shape"),
  ).toBeVisible();
});

test("partial filmstrip failure keeps good previews and offers an accessible retry", async ({
  page,
}) => {
  let failFirstPreview = true;
  await page.route("**/evidence*", async (route) => {
    const url = new URL(route.request().url());
    if (
      failFirstPreview &&
      url.searchParams.get("frame") === "0" &&
      url.searchParams.get("width") === "160" &&
      !url.searchParams.has("x_milli")
    ) {
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ detail: "temporary preview failure" }),
      });
      return;
    }
    await route.continue();
  });

  await openReview(page, "responsive");
  const retry = page.getByRole("button", {
    name: "Повторить загрузку превью",
  });
  await expect(retry).toBeVisible();
  await expect(page.locator(".filmstrip button.loaded").first()).toBeVisible();
  await expect(page.locator(".filmstrip button.failed")).toHaveAttribute(
    "aria-label",
    /превью недоступно/,
  );
  const retryBounds = await retry.boundingBox();
  expect(retryBounds?.height).toBeGreaterThanOrEqual(44);

  failFirstPreview = false;
  await retry.click();
  await expect(page.locator(".filmstrip button.failed")).toHaveCount(0);
  await expect(retry).toHaveCount(0);
});

test("active previous region requests one exact lazy crop", async ({
  page,
  request,
}) => {
  const packResponse = await request.get(
    `${baseURL("exact")}/api/v3/review/task-pack`,
  );
  expect(packResponse.ok()).toBeTruthy();
  const pack = await packResponse.json();
  const cropRequest = page.waitForRequest((candidate) => {
    const url = new URL(candidate.url());
    return (
      url.pathname.endsWith(
        `/artifacts/${pack.artifact.sha256}/evidence`,
      ) && url.searchParams.has("x_milli")
    );
  });

  await openReview(page, "exact");
  await expect(
    page.getByRole("img", {
      name: /Область прошлого замечания/,
    }),
  ).toHaveCount(0);
  await page
    .getByRole("button", { name: "Следующее замечание" })
    .click();
  const requestURL = new URL((await cropRequest).url());
  expect(requestURL.searchParams.get("size")).toBe(
    String(pack.artifact.size),
  );
  expect(requestURL.searchParams.get("frame")).toBe("4");
  expect(requestURL.searchParams.get("width")).toBe("160");
  expect(requestURL.searchParams.get("x_milli")).toBe("100");
  expect(requestURL.searchParams.get("y_milli")).toBe("160");
  expect(requestURL.searchParams.get("width_milli")).toBe("360");
  expect(requestURL.searchParams.get("height_milli")).toBe("240");
  await expect(
    page.getByRole("img", {
      name: "Область прошлого замечания, кадр 4",
    }),
  ).toBeVisible();
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
    await expect(
      page.locator(".review-time-track.previous"),
    ).toHaveCSS("height", "44px");
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
