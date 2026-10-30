import { expect, Page, test } from "@playwright/test";

/**
 * One-ticket happy path against the running Compose stack (fresh seed: `make seed`).
 * Operator starts an investigation and cannot approve; supervisor approves the exact refund;
 * the ledger shows exactly one simulated refund.
 */
async function login(page: Page, username: string, password: string) {
  await page.goto("/login");
  await page.getByRole("link", { name: "Sign in with Keycloak" }).click();
  await page.locator("#username").fill(username);
  await page.locator("#password").fill(password);
  await page.locator("#kc-login").click();
  await expect(page.getByTestId("whoami")).toContainText(username);
}

async function logout(page: Page) {
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/login|realms/);
  await page.context().clearCookies();
}

test("operator investigates T-101, supervisor approves the simulated refund once", async ({ page }) => {
  await login(page, "operator", "operator-demo");
  await expect(page.getByTestId("demo-banner")).toContainText("simulated");
  await expect(page.getByRole("link", { name: "Approvals" })).toHaveCount(0);

  await page.goto("/agent?ticket=T-101");
  await page.getByRole("button", { name: "Start investigation" }).click();
  await expect(page).toHaveURL(/\/runs\//);
  await expect(page.getByTestId("timeline")).toContainText("get_ticket");
  await expect(page.getByTestId("action-refund")).toContainText("₹1,200.00");
  await expect(page.getByTestId("action-refund")).toContainText("pending approval");
  const runUrl = page.url();

  // Operators cannot approve: the API refuses even if called directly.
  const direct = await page.request.get("/api/proxy/api/v1/approvals");
  expect(direct.status()).toBe(403);
  await logout(page);

  await login(page, "supervisor", "supervisor-demo");
  await page.goto("/approvals");
  await expect(page.getByTestId("pending-badge")).toHaveText("2");
  const group = page.getByTestId("approval-group-T-101");
  const card = group.getByTestId("approval-refund");
  await expect(card.getByTestId("refund-amount")).toHaveText("₹1,200.00");
  await card.getByRole("button", { name: "Approve" }).click();
  await expect(page.getByRole("status").filter({ hasText: "approved" })).toBeVisible();
  await expect(group.getByTestId("approval-refund")).toHaveCount(0);
  await expect(group.getByTestId("approval-send_reply")).toHaveCount(1);
  await expect(page.getByTestId("pending-badge")).toHaveText("1");

  await page.goto(runUrl);
  await expect(page.getByTestId("action-refund")).toContainText("completed");
  await page.reload(); // durable state survives a reload
  await expect(page.getByTestId("timeline")).toContainText("Executed refund (simulated)");

  await page.goto("/ledger");
  await expect(page.getByTestId("refunds-table").getByText("O-101")).toHaveCount(1);
});
