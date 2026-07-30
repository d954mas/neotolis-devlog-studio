import { expect } from "@playwright/test";
import type {
  APIRequestContext,
  Page,
  Request,
} from "@playwright/test";

export type Scenario =
  | "exact"
  | "compare"
  | "stale"
  | "mismatch"
  | "legacy"
  | "same"
  | "responsive";

type BlobRef = { sha256: string; size: number };

export type ReviewContextPayload = {
  artifact: BlobRef;
  timeline: BlobRef;
  check_report: BlobRef;
  constraints: BlobRef;
  latest_round: BlobRef;
  latest_verdict: {
    findings: Array<{
      finding_id: string;
      requires_change: boolean;
    }>;
  };
  items: Array<{ item_id: string }>;
  fps_num: number;
  fps_den: number;
  duration_ns: number;
};

type RuntimeState = {
  baseURLs: Record<Scenario, string>;
};

function runtimeState(): RuntimeState {
  const raw = process.env.DLSTUDIO_E2E_STATE;
  if (!raw) throw new Error("Playwright fixture state is unavailable");
  return JSON.parse(raw) as RuntimeState;
}

export function baseURL(scenario: Scenario): string {
  return runtimeState().baseURLs[scenario];
}

export async function reviewContext(
  request: APIRequestContext,
  scenario: Scenario,
): Promise<ReviewContextPayload> {
  const response = await request.get(
    `${baseURL(scenario)}/api/v3/review/context`,
  );
  expect(response.ok()).toBeTruthy();
  return (await response.json()) as ReviewContextPayload;
}

export async function openReview(
  page: Page,
  scenario: Scenario,
): Promise<void> {
  await page.goto(baseURL(scenario));
  await expect(
    page.getByRole("heading", { name: "Проверьте исправления" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "До исправления" }),
  ).toBeEnabled();
  await expect(
    page.getByRole("textbox", { name: "Комментарий" }),
  ).toBeEnabled();
}

export function postBody(
  context: ReviewContextPayload,
  { findingId }: { findingId: string },
) {
  const previous = context.latest_verdict.findings.filter(
    (finding) => finding.requires_change,
  );
  return {
    expected_artifact: context.artifact,
    expected_timeline: context.timeline,
    expected_check_report: context.check_report,
    expected_constraints: context.constraints,
    expected_latest_round: context.latest_round,
    resolutions: previous.map((finding) => ({
      previous_finding_id: finding.finding_id,
      status: "fixed",
      current_finding_id: null,
    })),
    outcome: "changes_requested",
    scope: ["visual", "audio", "constraints"],
    reviewer: "e2e.concurrent",
    reviewed_at: "2026-07-30T12:00:00Z",
    findings: [
      {
        finding_id: findingId,
        text: "A concurrent reviewer found another issue.",
        requires_change: true,
        locator: {
          start_frame: 0,
          end_frame_exclusive: 1,
          region: null,
          target_ids: ["visual.000"],
        },
      },
    ],
  };
}

export function isReviewPost(request: Request): boolean {
  return (
    request.method() === "POST" &&
    new URL(request.url()).pathname === "/api/v3/review"
  );
}

export async function expectNoHorizontalOverflow(
  page: Page,
): Promise<void> {
  await expect
    .poll(() =>
      page.evaluate(() => {
        const root = document.documentElement;
        return root.scrollWidth - root.clientWidth;
      }),
    )
    .toBeLessThanOrEqual(1);
}
