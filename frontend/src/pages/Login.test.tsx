import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider } from "../auth";
import Login from "./Login";

function renderLogin() {
  return render(
    <QueryClientProvider client={new QueryClient()}><MemoryRouter><AuthProvider><Login /></AuthProvider></MemoryRouter></QueryClientProvider>,
  );
}

describe("Login", () => {
  it("asks for a passcode only for engineers and blocks short usernames", async () => {
    renderLogin();
    const go = screen.getByRole("button", { name: "Continue" });
    expect(go).toBeDisabled();
    expect(screen.queryByLabelText("Engineer passcode")).not.toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Username"), "al");
    expect(go).toBeEnabled();
    await userEvent.click(screen.getByRole("tab", { name: "Support engineer" }));
    expect(screen.getByLabelText("Engineer passcode")).toBeInTheDocument();
  });
  it("shows the server's message when sign-in fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 403, statusText: "Forbidden", json: async () => ({ detail: "wrong engineer passcode" }) }));
    renderLogin();
    await userEvent.type(screen.getByLabelText("Username"), "enid");
    await userEvent.click(screen.getByRole("tab", { name: "Support engineer" }));
    await userEvent.type(screen.getByLabelText("Engineer passcode"), "nope");
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("wrong engineer passcode");
    vi.unstubAllGlobals();
  });
});
