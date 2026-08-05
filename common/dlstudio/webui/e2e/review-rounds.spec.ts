import { expect, test } from "@playwright/test";
import {
  baseURL,
  isReviewPost,
  openReview,
  postBody,
  reviewContext,
} from "./helpers";

test("submits exact refs and explicit links to previous findings", async ({
  page,
  request,
}) => {
  const context = await reviewContext(request, "exact");
  await openReview(page, "exact");

  await page
    .getByRole("button", { name: "Больше не актуально" })
    .click();
  await page
    .getByRole("button", { name: "Следующее замечание" })
    .click();
  await expect(
    page.getByRole("heading", { name: "Замечание 2 из 2" }),
  ).toBeVisible();

  await page.getByRole("button", { name: "Всё ещё не так" }).click();
  const note = page.getByRole("textbox", { name: "Комментарий" });
  await expect(note).toHaveValue(
    "Move the highlighted element away from the title.",
  );
  await note.fill("Move it farther from the title in the current version.");
  await page
    .getByRole("button", {
      name: "Отметить центральную область кадра",
    })
    .click();
  await page
    .getByRole("button", { name: "Сохранить комментарий" })
    .click();
  await expect(
    page.getByRole("button", {
      name: /Новый комментарий: Move it farther/,
    }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Предыдущее замечание" })
    .click();
  await expect(
    page.getByRole("heading", { name: "Замечание 1 из 2" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Удалить замечание 1" })
    .click();
  await expect(
    page.getByRole("heading", { name: "Замечание 2 из 2" }),
  ).toBeVisible();
  await expect(note).toHaveValue(
    "Move the highlighted element away from the title.",
  );
  await note.fill("Move it farther from the title in the current version.");
  await page
    .getByRole("button", { name: "Сохранить комментарий" })
    .click();

  const outgoing = page.waitForRequest(isReviewPost);
  const incoming = page.waitForResponse(
    (response) => isReviewPost(response.request()),
  );
  await page
    .getByRole("button", { name: "Отправить комментарии · 1" })
    .click();
  const [reviewRequest, reviewResponse] = await Promise.all([
    outgoing,
    incoming,
  ]);
  expect(reviewResponse.status()).toBe(200);
  const body = reviewRequest.postDataJSON();

  expect(body.expected_artifact).toEqual(context.artifact);
  expect(body.expected_timeline).toEqual(context.timeline);
  expect(body.expected_artifact_report).toEqual(context.artifact_report);
  expect(body.expected_publication_manifest).toEqual(
    context.publication_manifest,
  );
  expect(body.expected_check_report).toEqual(context.check_report);
  expect(body.expected_constraints).toEqual(context.constraints);
  expect(body.expected_latest_round).toEqual(context.latest_round);
  expect(body.outcome).toBe("changes_requested");
  expect(body.findings).toEqual([
    expect.objectContaining({
      finding_id: "studio.ui.001",
      text: "Move it farther from the title in the current version.",
      requires_change: true,
      locator: expect.objectContaining({
        region: {
          x_milli: 200,
          y_milli: 200,
          width_milli: 600,
          height_milli: 600,
        },
      }),
    }),
  ]);
  expect(body.resolutions).toEqual([
    {
      previous_finding_id: "review.previous.edge",
      status: "obsolete",
      current_finding_id: null,
    },
    {
      previous_finding_id: "review.previous.region",
      status: "still_wrong",
      current_finding_id: "studio.ui.001",
    },
  ]);

  const currentResponse = await request.get(
    `${baseURL("exact")}/api/v3/review/current`,
  );
  expect(currentResponse.ok()).toBeTruthy();
  const current = await currentResponse.json();
  expect(current.findings[0].finding_id).toBe("studio.ui.001");
  const packResponse = await request.get(
    `${baseURL("exact")}/api/v3/review/task-pack`,
  );
  expect(packResponse.ok()).toBeTruthy();
  const pack = await packResponse.json();
  expect(pack.review_round.resolutions).toEqual(body.resolutions);
});

test("a second client makes an unchanged pass stale and the UI stays in review", async ({
  page,
  request,
}) => {
  const context = await reviewContext(request, "stale");
  await openReview(page, "stale");

  const concurrent = await request.post(
    `${baseURL("stale")}/api/v3/review`,
    {
      data: postBody(context, { findingId: "e2e.concurrent.stale" }),
    },
  );
  expect(concurrent.status()).toBe(200);

  const staleResponse = page.waitForResponse(
    (response) => isReviewPost(response.request()),
  );
  await page
    .getByRole("button", { name: "Подтвердить: всё исправлено" })
    .click();
  const response = await staleResponse;
  expect(response.status()).toBe(409);
  expect(await response.json()).toEqual({
    detail: "latest review round changed",
  });
  await expect(page.getByRole("alert")).toContainText(
    "latest review round changed",
  );
  await expect(
    page.getByRole("heading", { name: "Замечания переданы" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Подтвердить: всё исправлено" }),
  ).toHaveCount(0);

  const statusResponse = await request.get(
    `${baseURL("stale")}/api/v3/status`,
  );
  const status = await statusResponse.json();
  expect(status.action).toBe("review");
  expect(status.current_stage).toBe("review");
  const currentResponse = await request.get(
    `${baseURL("stale")}/api/v3/review/current`,
  );
  const current = await currentResponse.json();
  expect(current.outcome).toBe("changes_requested");
  expect(current.findings[0].finding_id).toBe("e2e.concurrent.stale");
});

test("rejects a task pack whose latest round changed after context load", async ({
  page,
  request,
}) => {
  const original = await reviewContext(request, "mismatch");
  const originalCurrentResponse = await request.get(
    `${baseURL("mismatch")}/api/v3/review/current`,
  );
  expect(originalCurrentResponse.ok()).toBeTruthy();
  const originalCurrent = await originalCurrentResponse.text();
  await page.route(
    "**/api/v3/review/current",
    (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: originalCurrent,
      }),
    { times: 1 },
  );
  let advanced = false;
  await page.route("**/api/v3/review/task-pack", async (route) => {
    if (!advanced) {
      advanced = true;
      const concurrent = await request.post(
        `${baseURL("mismatch")}/api/v3/review`,
        {
          data: postBody(original, {
            findingId: "e2e.concurrent.mismatch",
          }),
        },
      );
      expect(concurrent.status()).toBe(200);
    }
    const latestPackResponse = await request.get(
      `${baseURL("mismatch")}/api/v3/review/task-pack`,
    );
    expect(latestPackResponse.ok()).toBeTruthy();
    const latestPack = await latestPackResponse.json();
    expect(latestPack.latest_round).not.toEqual(original.latest_round);
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(latestPack),
    });
  });

  await page.goto(baseURL("mismatch"));
  await expect(
    page.getByText(
      "Прошлая версия изменилась во время загрузки. Сравнение и подтверждение временно недоступны.",
    ),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "До исправления" }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Подтвердить: всё исправлено" }),
  ).toBeDisabled();
});

test("migrates the legacy array draft and preserves it across reload", async ({
  page,
  request,
}) => {
  const context = await reviewContext(request, "legacy");
  const legacyKey = [
    "dlstudio.review",
    context.artifact.sha256,
    context.timeline.sha256,
    context.check_report.sha256,
    context.constraints.sha256,
  ].join(".");
  const currentKey = [
    legacyKey,
    context.latest_round.sha256,
    context.latest_round.size,
  ].join(".");
  const legacyFinding = {
    finding_id: "legacy.draft.001",
    text: "This local draft must survive the UI upgrade.",
    requires_change: true,
    locator: {
      start_frame: 2,
      end_frame_exclusive: 3,
      region: null,
      target_ids: ["visual.000"],
    },
  };
  await page.addInitScript(
    ({ key, value }) => {
      localStorage.setItem(key, JSON.stringify(value));
    },
    { key: legacyKey, value: [legacyFinding] },
  );

  await openReview(page, "legacy");
  await expect(
    page.getByText("This local draft must survive the UI upgrade."),
  ).toBeVisible();
  const migrated = await page.evaluate((key) => {
    const value = localStorage.getItem(key);
    return value === null ? null : JSON.parse(value);
  }, currentKey);
  expect(migrated.findings).toEqual([legacyFinding]);

  await page.reload();
  await expect(
    page.getByText("This local draft must survive the UI upgrade."),
  ).toBeVisible();
  await expect(
    page.getByRole("textbox", { name: "Комментарий" }),
  ).toBeEnabled();
  const persisted = await page.evaluate((key) => {
    const value = localStorage.getItem(key);
    return value === null ? null : JSON.parse(value);
  }, currentKey);
  expect(persisted.findings).toEqual([legacyFinding]);

  await page
    .getByRole("button", { name: "Следующее замечание" })
    .click();
  await page.getByRole("button", { name: "Всё ещё не так" }).click();
  const note = page.getByRole("textbox", { name: "Комментарий" });
  await note.fill("This in-progress continuation must survive reload.");
  await page
    .getByRole("button", {
      name: "Отметить центральную область кадра",
    })
    .click();
  const selectionBeforeReload = await page
    .locator(".time-range-readout")
    .textContent();

  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Замечание 2 из 2" }),
  ).toBeVisible();
  await expect(note).toHaveValue(
    "This in-progress continuation must survive reload.",
  );
  await expect(
    page.getByRole("button", { name: "Убрать область" }),
  ).toBeVisible();
  await expect(page.locator(".time-range-readout")).toHaveText(
    selectionBeforeReload ?? "",
  );
  await page
    .getByRole("button", { name: "Сохранить комментарий" })
    .click();
  await expect(
    page.getByRole("button", {
      name: /Новый комментарий: This in-progress continuation/,
    }),
  ).toBeVisible();
});
