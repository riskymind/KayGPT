import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api-client";

import { renderWithClient } from "./test-utils";

const router = { replace: vi.fn(), push: vi.fn(), refresh: vi.fn() };
let next: string | null = null;
vi.mock("next/navigation", () => ({
  useRouter: () => router,
  useSearchParams: () => ({ get: () => next }),
}));

const login = vi.fn();
const register = vi.fn();
vi.mock("@/services", () => ({ authService: { login, register } }));

const { AuthForm } = await import("@/components/auth/auth-form");

beforeEach(() => {
  vi.clearAllMocks();
  next = null;
});

describe("AuthForm", () => {
  it("validates input before calling the API", async () => {
    const user = userEvent.setup();
    renderWithClient(<AuthForm mode="register" />);
    await user.type(screen.getByLabelText("Email"), "not-an-email");
    await user.type(screen.getByLabelText("Password"), "short");
    await user.click(screen.getByRole("button", { name: "Create account" }));
    expect(await screen.findByText("Enter a valid email address.")).toBeInTheDocument();
    expect(screen.getByText("Use at least 10 characters.")).toBeInTheDocument();
    expect(register).not.toHaveBeenCalled();
  });

  it("logs in and follows only safe relative redirects", async () => {
    const user = userEvent.setup();
    next = "//evil.example";
    login.mockResolvedValue({ user: { id: "1" }, csrf_token: "t" });
    renderWithClient(<AuthForm mode="login" />);
    await user.type(screen.getByLabelText("Email"), "kay@example.com");
    await user.type(screen.getByLabelText("Password"), "secret-password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/"));
    expect(login).toHaveBeenCalledWith("kay@example.com", "secret-password");
  });

  it("shows API errors", async () => {
    const user = userEvent.setup();
    login.mockRejectedValue(new ApiError(401, "invalid_credentials", "Invalid email or password."));
    renderWithClient(<AuthForm mode="login" />);
    await user.type(screen.getByLabelText("Email"), "kay@example.com");
    await user.type(screen.getByLabelText("Password"), "wrong-password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid email or password.");
  });
});
