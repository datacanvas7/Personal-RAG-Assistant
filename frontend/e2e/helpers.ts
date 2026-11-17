import { expect, type Page } from "@playwright/test";

export const PASSWORD = "a-reasonable-passphrase";

export function uniqueEmail(prefix = "user"): string {
  return `${prefix}-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`;
}

export async function register(page: Page, email: string, password = PASSWORD): Promise<void> {
  await page.goto("/register");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByLabel("Repeat password").fill(password);
  await page.getByRole("button", { name: /create account/i }).click();
  await expect(page).toHaveURL(/\/dashboard/);
}

export async function login(page: Page, email: string, password = PASSWORD): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page).toHaveURL(/\/dashboard/);
}

export async function signOut(page: Page): Promise<void> {
  await page.getByRole("button", { name: "Account menu" }).click();
  await page.getByRole("menuitem", { name: /sign out/i }).click();
  await expect(page).toHaveURL(/\/login/);
}

/** Upload a text file through the real file input and wait until it is searchable. */
export async function uploadAndWaitUntilReady(page: Page, name: string, text: string): Promise<void> {
  await page.goto("/documents");
  await page.getByTestId("file-input").setInputFiles({
    name,
    mimeType: "text/plain",
    buffer: Buffer.from(text, "utf-8"),
  });
  const row = page.getByTestId("document-row").filter({ hasText: name });
  await expect(row).toBeVisible();
  await expect(row.locator('[data-status="ready"]')).toBeVisible({ timeout: 45_000 });
}

// One short sentence on purpose: retrieval in the test server uses a bag-of-words embedder,
// where a long chunk that mixes topics scores too low against a question about one of them,
// and the stand-in model quotes the first sentence of the best passage.
export const POLICY_TEXT = "Every employee must change their password every ninety days.\n";

export const PASSWORD_QUESTION = "How often must every employee change their password?";
