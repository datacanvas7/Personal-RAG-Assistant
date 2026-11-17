import { expect, test } from "@playwright/test";

import {
  PASSWORD,
  PASSWORD_QUESTION,
  POLICY_TEXT,
  login,
  register,
  signOut,
  uniqueEmail,
  uploadAndWaitUntilReady,
} from "./helpers";

/**
 * The whole user journey in one browser session against a real API and database:
 * register -> upload -> library -> chat (streaming) -> citations -> history -> sign out.
 * Steps share state (the account and its documents), so they run in order.
 */
test.describe.configure({ mode: "serial" });

const email = uniqueEmail("journey");

test("signed-out visitors are sent to the login page", async ({ page }) => {
  await page.goto("/chat");
  await expect(page).toHaveURL(/\/login/);
  await page.goto("/documents");
  await expect(page).toHaveURL(/\/login/);
});

test("registration validates input, then creates the account and signs in", async ({ page }) => {
  await page.goto("/register");
  await page.getByLabel("Email").fill("not-an-email");
  await page.getByLabel("Password", { exact: true }).fill("short");
  await page.getByLabel("Repeat password").fill("different");
  await page.getByRole("button", { name: /create account/i }).click();
  await expect(page).toHaveURL(/\/register/);
  await expect(page.getByRole("alert").first()).toBeVisible();

  await register(page, email);
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
});

test("signing out and back in works, and a wrong password is refused", async ({ page }) => {
  await login(page, email);
  await signOut(page);

  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill("wrong-password-entirely");
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page).toHaveURL(/\/login/);
  await expect(page.getByRole("alert")).toBeVisible();

  await login(page, email, PASSWORD);
});

test("a document can be uploaded, found, filtered and (later) deleted from the library", async ({ page }) => {
  await login(page, email);
  await uploadAndWaitUntilReady(page, "policy.txt", POLICY_TEXT);

  await page.getByLabel("Search documents").fill("polic");
  await expect(page.getByTestId("document-row")).toHaveCount(1);
  await page.getByLabel("Search documents").fill("nothing-like-this");
  await expect(page.getByText("No documents match your search.")).toBeVisible();
  await page.getByLabel("Search documents").fill("");

  await uploadAndWaitUntilReady(page, "scratch.txt", "Throwaway file. It will be deleted again.\n");
  await expect(page.getByTestId("document-row")).toHaveCount(2);
  await page.getByRole("button", { name: "Delete scratch.txt" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Delete" }).click();
  await expect(page.getByTestId("document-row")).toHaveCount(1);
});

test("a question is answered as a stream, with a clickable citation and a source list", async ({ page }) => {
  await login(page, email);
  await page.goto("/chat");
  await expect(page.getByTestId("empty-chat")).toBeVisible();

  // Sample the length of the answer while it streams. If something between the API and the
  // browser buffered the stream (compression in the Next server did once), the answer would
  // jump from nothing to complete and only one or two distinct lengths would be seen.
  await page.evaluate(() => {
    const seen = new Set<number>();
    Object.assign(window, { __streamLengths: seen });
    setInterval(() => {
      const bubble = document.querySelector('[data-role="assistant"][data-streaming="true"]');
      if (bubble) seen.add(bubble.textContent?.length ?? 0);
    }, 10);
  });

  await page.getByTestId("chat-input").fill(PASSWORD_QUESTION);
  await page.getByTestId("chat-input").press("Enter");

  // The question appears immediately and the answer arrives piece by piece.
  await expect(page.locator('[data-role="user"]').first()).toContainText(PASSWORD_QUESTION);
  await expect(page.locator('[data-role="assistant"][data-streaming="true"]')).toBeVisible();

  const answer = page.locator('[data-role="assistant"][data-streaming="false"]').first();
  await expect(answer).toContainText("ninety days");
  await expect(answer.getByTestId("citation").first()).toHaveText("1");
  const distinctLengths = await page.evaluate(
    () => (window as unknown as { __streamLengths: Set<number> }).__streamLengths.size,
  );
  expect(distinctLengths, "the answer should grow in several steps, not appear all at once").toBeGreaterThanOrEqual(4);

  // The conversation was created, named after the question, and is the open one.
  await expect(page).toHaveURL(/\/chat\?c=[0-9a-f-]{36}/);
  const item = page.getByTestId("conversation-item").first();
  await expect(item).toContainText("How often must every employee");
  await expect(item).toHaveAttribute("data-active", "true");

  // Sources are collapsed until asked for; the chip opens and highlights its entry.
  await expect(answer.getByTestId("source-item")).toHaveCount(0);
  await answer.getByTestId("citation").first().click();
  const source = answer.getByTestId("source-item").first();
  await expect(source).toContainText("policy.txt");
  await expect(source).toHaveAttribute("data-highlighted", "true");
});

test("history survives a reload, and a follow-up continues the same conversation", async ({ page }) => {
  await login(page, email);
  await page.goto("/chat");
  await page.getByTestId("conversation-item").first().getByRole("link").click();
  await expect(page.locator('[data-role="user"]')).toHaveCount(1);

  await page.reload();
  await expect(page.locator('[data-role="user"]')).toHaveCount(1);
  await expect(page.locator('[data-role="assistant"]')).toHaveCount(1);
  await expect(page.getByTestId("citation").first()).toBeVisible();

  const url = page.url();
  await page.getByTestId("chat-input").fill("What are the password length rules?");
  await page.getByTestId("send-button").click();
  await expect(page.locator('[data-role="assistant"][data-streaming="false"]')).toHaveCount(2);
  await expect(page.locator('[data-role="user"]')).toHaveCount(2);
  expect(page.url()).toBe(url);
});

test("an answer can be copied", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await login(page, email);
  await page.goto("/chat");
  await page.getByTestId("conversation-item").first().getByRole("link").click();
  await page.getByRole("button", { name: "Copy answer" }).first().click();
  await expect(page.getByRole("button", { name: "Copied" })).toBeVisible();
  const copied = await page.evaluate(() => navigator.clipboard.readText());
  expect(copied).toContain("ninety days");
});

test("a failed answer shows an error with Retry, and nothing is saved for it", async ({ page }) => {
  await login(page, email);
  await page.goto("/chat");
  await page.getByTestId("new-chat").click();
  await expect(page).toHaveURL(/\/chat$/);

  // The model is only called when retrieval finds something, so the question must match the
  // uploaded document; the "/fail" marker makes the stand-in model error out mid-stream.
  await page.getByTestId("chat-input").fill(`${PASSWORD_QUESTION} /fail`);
  await page.getByTestId("send-button").click();
  await expect(page.getByTestId("chat-error")).toBeVisible();
  await expect(page.getByRole("button", { name: "Retry" })).toBeVisible();

  await page.getByRole("button", { name: "Dismiss" }).click();
  await expect(page.getByTestId("chat-error")).toHaveCount(0);

  // Reloading shows an empty conversation: the failed exchange was never stored.
  await page.reload();
  await expect(page.locator('[data-role="user"]')).toHaveCount(0);
});

test("questions can be limited to chosen documents", async ({ page }) => {
  await login(page, email);
  await uploadAndWaitUntilReady(
    page,
    "travel.txt",
    "Travel policy. Flights must be booked at least fourteen days in advance.\n",
  );

  await page.goto("/chat");
  await page.getByTestId("new-chat").click();
  await page.getByTestId("scope-button").click();
  // Everything starts ticked; unticking policy.txt leaves only travel.txt in scope.
  await page.getByTestId("scope-option").and(page.getByLabel("policy.txt")).uncheck();
  await expect(page.getByTestId("scope-button")).toContainText("travel.txt");
  await page.getByTestId("scope-button").click();

  await page.getByTestId("chat-input").fill(PASSWORD_QUESTION);
  await page.getByTestId("send-button").click();
  // The password policy is in policy.txt only, so a travel-only search cannot find it.
  const answer = page.locator('[data-role="assistant"][data-streaming="false"]').first();
  await expect(answer).toContainText("couldn't find");
  await expect(answer.getByTestId("citation")).toHaveCount(0);
});

test("conversations can be renamed and deleted", async ({ page }) => {
  await login(page, email);
  await page.goto("/chat");
  // Earlier steps asked the same question in new conversations, so several share this title.
  const first = page
    .getByTestId("conversation-item")
    .filter({ hasText: "How often must every employee" })
    .first();
  await first.hover();
  await first.getByRole("button", { name: /^Rename/ }).click();
  await page.getByLabel("Conversation title").fill("Password rules");
  await page.getByLabel("Conversation title").press("Enter");
  await expect(page.getByTestId("conversation-item").filter({ hasText: "Password rules" })).toBeVisible();

  const renamed = page.getByTestId("conversation-item").filter({ hasText: "Password rules" });
  await renamed.hover();
  await renamed.getByRole("button", { name: /^Delete/ }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Delete" }).click();
  await expect(page.getByTestId("conversation-item").filter({ hasText: "Password rules" })).toHaveCount(0);
});

test("another user cannot see this user's documents or conversations", async ({ browser }) => {
  const context = await browser.newContext();
  const page = await context.newPage();
  await register(page, uniqueEmail("other"));
  await page.goto("/documents");
  await expect(page.getByText("No documents yet")).toBeVisible();
  await page.goto("/chat");
  await expect(page.getByTestId("empty-no-documents")).toBeVisible();
  await expect(page.getByTestId("conversation-item")).toHaveCount(0);
  await context.close();
});

test("the theme can be switched and is remembered", async ({ page }) => {
  await login(page, email);
  await page.getByRole("button", { name: /theme/i }).first().click();
  const toggled = await page.evaluate(() => document.documentElement.classList.contains("dark"));
  await page.reload();
  expect(await page.evaluate(() => document.documentElement.classList.contains("dark"))).toBe(toggled);
});
