import { expect, test } from "@playwright/test";

import { PASSWORD, lastAssistant, register, send, uniqueEmail } from "./helpers";

test("redirects unauthenticated visitors to login", async ({ page }) => {
  await page.goto("/c/00000000-0000-0000-0000-000000000000");
  await expect(page).toHaveURL(/\/login\?next=/);
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
});

test("streams a reply, persists it, and survives a reload", async ({ page }) => {
  await register(page);
  await send(page, "Hello KayGPT, nice to meet you");

  const answer = lastAssistant(page);
  await expect(answer).toHaveAttribute("aria-busy", "true"); // still streaming
  await expect(answer).toContainText("Echo: Hello KayGPT, nice to meet you");
  await expect(answer).toHaveAttribute("aria-busy", "false");
  await expect(page).toHaveURL(/\/c\/[0-9a-f-]{36}$/);

  // Sidebar shows the new conversation titled from the first message.
  await expect(page.getByRole("link", { name: "Hello KayGPT, nice to meet you" })).toBeVisible();

  await page.reload();
  await expect(page.getByTestId("message-user")).toContainText("Hello KayGPT, nice to meet you");
  await expect(lastAssistant(page)).toContainText("Echo: Hello KayGPT");
});

test("shows tool progress and the tool result", async ({ page }) => {
  await register(page);
  await send(page, "calculate 125 * 48 / 6");
  await expect(lastAssistant(page).getByText("Calculator", { exact: true })).toBeVisible();
  await expect(lastAssistant(page)).toContainText("Result from calculator: 1000");
  await page.reload();
  await expect(lastAssistant(page).getByText("Calculator", { exact: true })).toBeVisible();
});

test("stop generation keeps the partial answer", async ({ page }) => {
  await register(page);
  await send(page, Array.from({ length: 300 }, (_, i) => `word${i}`).join(" "));
  await expect(lastAssistant(page)).toContainText("word5");
  await page.getByRole("button", { name: "Stop generating" }).click();
  await expect(page.getByText("Generation stopped")).toBeVisible();
  await expect(page.getByRole("button", { name: "Send message" })).toBeVisible();
  await expect(lastAssistant(page)).not.toContainText("word299");
});

test("regenerate replaces the last answer", async ({ page }) => {
  await register(page);
  await send(page, "first question");
  await expect(lastAssistant(page)).toContainText("Echo: first question");
  await lastAssistant(page).hover();
  await page.getByRole("button", { name: "Regenerate response" }).click();
  await expect(lastAssistant(page)).toContainText("Echo: first question");
  await expect(page.getByTestId("message-assistant")).toHaveCount(1);
});

test("switches, renames and deletes conversations", async ({ page }) => {
  await register(page);
  await send(page, "alpha conversation");
  await expect(lastAssistant(page)).toContainText("Echo: alpha conversation");
  await page.getByRole("button", { name: "New chat" }).click();
  await expect(page.getByRole("heading", { name: "How can I help you today?" })).toBeVisible();
  await send(page, "beta conversation");
  await expect(lastAssistant(page)).toContainText("Echo: beta conversation");

  await page.getByRole("link", { name: "alpha conversation" }).click();
  await expect(page.getByTestId("message-user")).toHaveText(/alpha conversation/);

  await page.getByRole("button", { name: "Actions for alpha conversation" }).click();
  await page.getByRole("menuitem", { name: "Rename" }).click();
  await page.getByLabel("Chat title").fill("Renamed alpha");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("link", { name: "Renamed alpha" })).toBeVisible();

  await page.getByRole("button", { name: "Actions for Renamed alpha" }).click();
  await page.getByRole("menuitem", { name: "Delete" }).click();
  await page.getByRole("button", { name: "Delete" }).click();
  await expect(page.getByRole("link", { name: "Renamed alpha" })).toHaveCount(0);
  await expect(page).toHaveURL(/\/$/);

  await page.getByPlaceholder("Search chats").fill("beta");
  await expect(page.getByRole("link", { name: "beta conversation" })).toBeVisible();
});

test("uploads a document and answers from it", async ({ page }) => {
  await register(page);
  await page.getByTestId("file-input").setInputFiles({
    name: "handbook.md",
    mimeType: "text/markdown",
    buffer: Buffer.from("# Handbook\nThe office mascot is a tortoise named Ada."),
  });
  const chip = page.getByRole("list", { name: "Documents in this chat" }).getByText("handbook.md");
  await expect(chip).toBeVisible();
  await expect(page.getByLabel("Ready")).toBeVisible();

  await send(page, "search docs office mascot tortoise");
  await expect(lastAssistant(page)).toContainText("tortoise named Ada");
  await expect(lastAssistant(page)).toContainText("Source 1: handbook.md");

  await page.getByRole("button", { name: "Documents" }).first().click();
  await expect(page.getByRole("list", { name: "Uploaded documents" })).toContainText("handbook.md");
});

test("rejects unsupported uploads with a clear message", async ({ page }) => {
  await register(page);
  await page.getByTestId("file-input").setInputFiles({
    name: "notes.txt",
    mimeType: "text/plain",
    buffer: Buffer.from([0, 1, 2, 3]),
  });
  await expect(page.getByText(/Upload failed: Text file contains binary data/)).toBeVisible();
});

test("memory persists across conversations and can be managed in settings", async ({ page }) => {
  await register(page);
  await send(page, "remember my favourite colour is teal");
  await expect(lastAssistant(page)).toContainText("Memory saved successfully.");
  await page.getByRole("button", { name: "New chat" }).click();
  await send(page, "recall favourite colour");
  await expect(lastAssistant(page)).toContainText("my favourite colour is teal");

  await page.getByRole("button", { name: /e2e-.*@example\.com/ }).click();
  await page.getByRole("menuitem", { name: "Settings" }).click();
  await page.getByRole("tab", { name: "Memory" }).click();
  const memories = page.getByRole("list", { name: "Memories" });
  await expect(memories.getByText("my favourite colour is teal")).toBeVisible();
  await memories.getByRole("button", { name: /Forget/ }).click();
  await expect(page.getByText("No memories yet.")).toBeVisible();
});

test("sign out and sign back in", async ({ page }) => {
  const email = uniqueEmail();
  await register(page, email);
  await page.getByRole("button", { name: email }).click();
  await page.getByRole("menuitem", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login/);

  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("wrong-password-123");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText("Invalid email or password.")).toBeVisible();
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "How can I help you today?" })).toBeVisible();
});

test("mobile layout opens the sidebar as a drawer @mobile", async ({ page }) => {
  await register(page);
  await expect(page.getByRole("navigation", { name: "Sidebar" })).toBeHidden();
  await page.getByRole("button", { name: "Open sidebar" }).click();
  await expect(page.getByRole("navigation", { name: "Sidebar" })).toBeVisible();
  await page.keyboard.press("Escape");
  await send(page, "hello from my phone");
  await expect(lastAssistant(page)).toContainText("Echo: hello from my phone");
});
