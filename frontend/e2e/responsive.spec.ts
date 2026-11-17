import { expect, test } from "@playwright/test";

import { PASSWORD_QUESTION, POLICY_TEXT, register, uniqueEmail, uploadAndWaitUntilReady } from "./helpers";

/** On a phone: bottom tab bar, no sideways scrolling, and the chat is usable. */
test("the app works at phone width", async ({ page }) => {
  await register(page, uniqueEmail("phone"));
  await uploadAndWaitUntilReady(page, "policy.txt", POLICY_TEXT);

  await page.goto("/chat");
  await expect(page.getByRole("navigation", { name: "Main" }).last()).toBeVisible();

  await page.getByTestId("chat-input").fill(PASSWORD_QUESTION);
  await page.getByTestId("send-button").click();
  const answer = page.locator('[data-role="assistant"][data-streaming="false"]').first();
  await expect(answer).toContainText("ninety days");

  // The conversation list is behind a button on small screens.
  // (The desktop sidebar stays in the page but is hidden, so count only what can be seen.)
  const visibleItems = page.locator('[data-testid="conversation-item"]:visible');
  await expect(visibleItems).toHaveCount(0);
  await page.getByRole("button", { name: "Conversations" }).click();
  await expect(visibleItems).toHaveCount(1);

  for (const path of ["/dashboard", "/documents", "/chat", "/settings"]) {
    await page.goto(path);
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow, `horizontal overflow on ${path}`).toBeLessThanOrEqual(1);
  }
});
