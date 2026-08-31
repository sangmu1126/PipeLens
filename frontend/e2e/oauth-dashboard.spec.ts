import { expect, test } from "@playwright/test";

test("completes OAuth, enters the dashboard, and logs out", async ({ context, page }) => {
  await page.goto("/");
  await expect(page.getByRole("link", { name: /GitHub로 로그인/ })).toBeVisible();

  await page.getByRole("link", { name: /GitHub로 로그인/ }).click();
  await expect(page).toHaveURL(/^http:\/\/127\.0\.0\.1:8000\/mock-github\/login\/oauth\/authorize/);
  const authorizationUrl = new URL(page.url());
  expect(authorizationUrl.searchParams.get("client_id")).toBe("browser-e2e-client");
  expect(authorizationUrl.searchParams.get("state")).toBeTruthy();
  expect(authorizationUrl.searchParams.get("redirect_uri")).toBe(
    "http://127.0.0.1:5173/auth/github/callback",
  );
  await page.getByRole("link", { name: "PipeLens 승인" }).click();

  await expect(page).toHaveURL("http://127.0.0.1:5173/");
  await expect(page.getByRole("heading", { name: /실패의 첫 원인을/ })).toBeVisible();
  await expect(page.getByText("octocat", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "최근 분석" })).toBeVisible();

  const cookies = await context.cookies();
  const sessionCookie = cookies.find((cookie) => cookie.name === "pipelens_session");
  expect(sessionCookie).toMatchObject({ httpOnly: true, sameSite: "Lax" });
  expect(cookies.some((cookie) => cookie.name === "pipelens_oauth_state")).toBe(false);

  await page.getByRole("button", { name: "로그아웃" }).click();
  await expect(page.getByRole("link", { name: /GitHub로 로그인/ })).toBeVisible();
  await expect.poll(async () =>
    (await context.cookies()).some((cookie) => cookie.name === "pipelens_session"),
  ).toBe(false);
});
