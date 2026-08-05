import { expect, test } from "@playwright/test";
import { baseURL } from "./helpers";

const blockers = [
  {
    rule: "audio.voice.required",
    owner: "Авторский монтаж",
    action: "AudioClip",
  },
  {
    rule: "audio.voice.silent",
    owner: "Финальный звук",
    action: "слышимого сигнала",
  },
  {
    rule: "package.cover.required",
    owner: "Publication package",
    action: "обязательную обложку",
  },
] as const;

for (const blocker of blockers) {
  test(`${blocker.rule} shows its owner and recovery action`, async ({ page }) => {
    await page.route("**/api/v3/status", (route) => route.fulfill({
      status: 200,
      json: {
        action: "advance",
        completed: false,
        current_stage: "prepare",
        production_id: "fixture.blocker",
        stage_order: ["prepare", "draft", "final", "review", "package", "deliver"],
        workflow: {
          attempts: [{
            error: `${blocker.rule}: blocked by regression fixture`,
            inputs: [],
            operation_id: `fixture.${blocker.rule}`,
            outputs: [],
            stage: "prepare",
            state: "failed",
          }],
          delivery_receipt: null,
          eligible_candidate: null,
          kind: "reel",
          production_id: "fixture.blocker",
          revision: 3,
          run_id: "run.blocker",
        },
      },
    }));

    await page.goto(baseURL("exact"));

    const alert = page.getByRole("alert");
    await expect(alert).toContainText(blocker.rule);
    await expect(alert).toContainText(blocker.owner);
    await expect(alert).toContainText(blocker.action);
  });
}
