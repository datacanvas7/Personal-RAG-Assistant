// Captures the README screenshots against a running e2e stack (see playwright.config.ts):
//   node scripts/screenshots.mjs            -> ../docs/screenshots/*.png
// PW_CHANNEL=msedge|chrome uses an installed browser; PW_BASE_URL overrides the address.
import { mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { chromium, devices } from "@playwright/test";

const base = process.env.PW_BASE_URL ?? "http://127.0.0.1:3100";
const out = new URL("../../docs/screenshots/", import.meta.url);
await mkdir(fileURLToPath(out), { recursive: true });
const shot = (page, name) => page.screenshot({ path: fileURLToPath(new URL(name, out)) });

const browser = await chromium.launch({ channel: process.env.PW_CHANNEL || undefined });
const email = `shots-${Date.now()}@example.com`;
const password = "a-reasonable-passphrase";
const policy = [
  "Every employee must change their password every ninety days.\n",
];

async function signUp(page) {
  await page.goto(`${base}/register`);
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByLabel("Repeat password").fill(password);
  await page.getByRole("button", { name: /create account/i }).click();
  await page.waitForURL(/dashboard/);
}

const desktop = await browser.newContext({ viewport: { width: 1360, height: 840 }, deviceScaleFactor: 1 });
const page = await desktop.newPage();
await signUp(page);
await page.goto(`${base}/documents`);
await page.getByTestId("file-input").setInputFiles({
  name: "security-policy.txt",
  mimeType: "text/plain",
  buffer: Buffer.from(policy.join(""), "utf-8"),
});
await page.locator('[data-status="ready"]').first().waitFor({ timeout: 60_000 });
await shot(page, "documents.png");

await page.goto(`${base}/chat`);
await page.getByTestId("chat-input").fill("How often must every employee change their password?");
await page.getByTestId("send-button").click();
await page.locator('[data-role="assistant"][data-streaming="false"]').first().waitFor();
await page.getByTestId("citation").first().click();
await shot(page, "chat.png");
await page.goto(`${base}/dashboard`);
await page.waitForTimeout(800);
await shot(page, "dashboard.png");

const phone = await browser.newContext({ ...devices["Pixel 7"] });
const mobile = await phone.newPage();
await mobile.goto(`${base}/login`);
await mobile.getByLabel("Email").fill(email);
await mobile.getByLabel("Password", { exact: true }).fill(password);
await mobile.getByRole("button", { name: /sign in/i }).click();
await mobile.waitForURL(/dashboard/);
await mobile.goto(`${base}/chat`);
await mobile.getByTestId("conversation-item").first().waitFor({ state: "attached" });
await mobile.getByRole("button", { name: "Conversations" }).click();
await mobile.waitForTimeout(400);
await shot(mobile, "chat-mobile.png");

await browser.close();
console.log("screenshots written to docs/screenshots");
