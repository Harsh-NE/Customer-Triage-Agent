import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { setToken, type Attachment, type ConversationView } from "../api";
import ChatPage from "./ChatPage";

const READ: Attachment = {
  id: "0123456789abcdef.png",
  ocr: { ok: true, text: "ERROR: OOMKilled - Exit code 137", confidence: 0.93, engine: "tesseract", reason: null, latency_ms: 900,
         error_messages: ["ERROR: OOMKilled - Exit code 137"], exit_codes: ["exit code 137"], low_confidence: false },
};
const UNREADABLE: Attachment = { id: "fedcba9876543210.png", ocr: { ...READ.ocr, ok: false, text: "", confidence: null, engine: null, reason: "no_engine", error_messages: [], exit_codes: [] } };
const view = (text: string, attachment?: object): ConversationView => ({
  id: "C-1", title: text, status: "active", escalated: false, created_at: "2026-11-02T10:00:00Z", updated_at: "2026-11-02T10:00:00Z", closed_at: null,
  duration_s: 1, rating: null, helpful: null, resolved_by: null, can_reply: true, feedback: { rating: null, helpful: null, comment: null }, assigned: false,
  messages: [{ id: 1, role: "customer", kind: "text", content: text, payload: attachment ? { attachment } : {}, created_at: "2026-11-02T10:00:00Z" }],
});

function mockServer(attachment: Attachment) {
  const calls: { url: string; init: RequestInit }[] = [];
  const fn = vi.fn(async (url: string, init: RequestInit = {}) => {
    calls.push({ url, init });
    if (url === "/api/attachments") return { ok: true, status: 201, statusText: "", json: async () => attachment };
    if (url === "/api/conversations") return { ok: true, status: 201, statusText: "", json: async () => view("sent") };
    return { ok: true, status: 200, statusText: "", json: async () => view("sent"), blob: async () => new Blob(["x"]) };
  });
  vi.stubGlobal("fetch", fn);
  return calls;
}

function renderChat() {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={["/chat"]}><Routes><Route path="/chat" element={<ChatPage />} /><Route path="/chat/:id" element={<ChatPage />} /></Routes></MemoryRouter>
    </QueryClientProvider>,
  );
}
const png = () => new File([new Uint8Array([137, 80, 78, 71])], "oom.png", { type: "image/png" });

beforeEach(() => {
  setToken("tok");
  vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn(() => "blob:preview"), revokeObjectURL: vi.fn() }));
});
afterEach(() => { vi.unstubAllGlobals(); setToken(null); });

describe("ChatPage screenshot attachment", () => {
  it("reads the screenshot, lets the customer correct the text, and sends the id with the corrected text", async () => {
    const calls = mockServer(READ);
    renderChat();
    await userEvent.upload(screen.getByTestId("screenshot-input"), png());
    const box = await screen.findByLabelText("Text from the screenshot");
    expect(box).toHaveValue("ERROR: OOMKilled - Exit code 137");
    expect(screen.getByText(/what I read from your screenshot/i)).toBeInTheDocument();
    const upload = calls.find((c) => c.url === "/api/attachments")!;
    expect(upload.init.body).toBeInstanceOf(FormData);
    expect((upload.init.headers as Record<string, string>)["Content-Type"]).toBeUndefined();     // the browser sets the multipart boundary
    await userEvent.clear(box);
    await userEvent.type(box, "ERROR: OOMKilled - Exit code 137 (container web)");
    await userEvent.type(screen.getByLabelText("Message"), "my container keeps dying");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(calls.some((c) => c.url === "/api/conversations")).toBe(true));
    const body = JSON.parse(calls.find((c) => c.url === "/api/conversations")!.init.body as string);
    expect(body).toEqual({ message: "my container keeps dying", attachment_id: READ.id, screenshot_text: "ERROR: OOMKilled - Exit code 137 (container web)" });
  });

  it("can send a screenshot on its own, and removing it clears the card", async () => {
    const calls = mockServer(READ);
    renderChat();
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
    await userEvent.upload(screen.getByTestId("screenshot-input"), png());
    await screen.findByTestId("screenshot-card");
    expect(screen.getByRole("button", { name: "Send" })).toBeEnabled();
    await userEvent.click(screen.getByRole("button", { name: "Remove screenshot" }));
    expect(screen.queryByTestId("screenshot-card")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
    await userEvent.upload(screen.getByTestId("screenshot-input"), png());
    await screen.findByTestId("screenshot-card");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(calls.some((c) => c.url === "/api/conversations")).toBe(true));
    expect(JSON.parse(calls.find((c) => c.url === "/api/conversations")!.init.body as string)).toMatchObject({ message: "", attachment_id: READ.id });
  });

  it("says so when nothing could be read and will not send an empty screenshot", async () => {
    mockServer(UNREADABLE);
    renderChat();
    await userEvent.upload(screen.getByTestId("screenshot-input"), png());
    expect(await screen.findByRole("alert")).toHaveTextContent(/couldn't read any text/i);
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();                          // nothing typed anywhere yet
    await userEvent.type(screen.getByLabelText("Text from the screenshot"), "Cannot connect to the Docker daemon");
    expect(screen.getByRole("button", { name: "Send" })).toBeEnabled();
  });

  it("shows the server's reason when the file is refused", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false, status: 422, statusText: "", json: async () => ({ detail: "That file is not an image I can open. Please attach a PNG or JPG screenshot." }) })));
    renderChat();
    await userEvent.upload(screen.getByTestId("screenshot-input"), new File(["MZ"], "x.png", { type: "image/png" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/not an image/i);
    expect(screen.queryByTestId("screenshot-card")).not.toBeInTheDocument();
  });
});
