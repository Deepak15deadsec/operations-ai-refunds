import { expect, Page, test } from "@playwright/test";

/**
 * Agent analytics dashboard against the running Compose stack. Asserts the page renders its
 * telemetry sections and the evaluation-suite results, independent of how many runs exist, so it
 * passes on a fresh seed and on a populated tenant alike.
 */
async function login(page: Page, username: string, password: string) {
  await page.goto("/login");
  await page.getByRole("link", { name: "Sign in with Keycloak" }).click();
  await page.locator("#username").fill(username);
  await page.locator("#password").fill(password);
  await page.locator("#kc-login").click();
  await expect(page.getByTestId("whoami")).toContainText(username);
}

test("operator sees the agent analytics dashboard and evaluation results", async ({ page }) => {
  await login(page, "operator", "operator-demo");

  await page.getByRole("link", { name: "Analytics" }).click();
  await expect(page).toHaveURL(/\/analytics/);
  await expect(page.getByRole("heading", { name: "Agent analytics" })).toBeVisible();

  // Headline tiles and telemetry sections.
  await expect(page.getByText("Investigations", { exact: true })).toBeVisible();
  await expect(page.getByText("Agent latency p50", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Run outcomes" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Tool reliability" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Model usage" })).toBeVisible();

  // Time-window selector is interactive.
  await page.getByRole("tab", { name: "7d" }).click();
  await expect(page.getByRole("tab", { name: "7d" })).toHaveAttribute("aria-selected", "true");

  // Evaluation suite is served from the committed report artifact.
  await expect(page.getByRole("heading", { name: "Evaluation suite" })).toBeVisible();
  await expect(page.getByText(/\d+\s*\/\s*\d+ scenarios/)).toBeVisible();
  await expect(page.getByText("Unapproved writes")).toBeVisible();
  await expect(page.getByText("Policy violations")).toBeVisible();
});
