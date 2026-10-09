import { api, ApiError, getToken, setToken } from "./api";

function mockFetch(status: number, body: unknown) {
  const fn = vi.fn().mockResolvedValue({ ok: status < 400, status, statusText: "x", json: async () => body });
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => { vi.unstubAllGlobals(); setToken(null); });

describe("api client", () => {
  it("sends the bearer token and JSON body", async () => {
    setToken("tok123");
    const f = mockFetch(200, { id: "C-1" });
    await api.start("hello");
    const [url, init] = f.mock.calls[0];
    expect(url).toBe("/api/conversations");
    expect(init.method).toBe("POST");
    expect(init.headers.Authorization).toBe("Bearer tok123");
    expect(JSON.parse(init.body)).toEqual({ message: "hello" });
  });
  it("turns error responses into ApiError with the server's detail", async () => {
    mockFetch(409, { detail: "this conversation is resolved; start a new one" });
    await expect(api.send("C-1", { text: "x" })).rejects.toMatchObject({ status: 409, message: "this conversation is resolved; start a new one" });
    mockFetch(422, { detail: [{ msg: "String should have at least 2 characters" }] });
    await expect(api.login("a", "customer")).rejects.toBeInstanceOf(ApiError);
  });
  it("clears the token and announces expiry on 401", async () => {
    setToken("old");
    const seen = vi.fn();
    window.addEventListener("auth:expired", seen);
    mockFetch(401, { detail: "invalid or expired token" });
    await expect(api.me()).rejects.toMatchObject({ status: 401 });
    expect(getToken()).toBeNull();
    expect(seen).toHaveBeenCalledTimes(1);
    window.removeEventListener("auth:expired", seen);
  });
  it("builds case filters without empty parameters", async () => {
    const f = mockFetch(200, { total: 0, cases: [] });
    await api.cases({ status: "escalated", priority: "", q: "pull" });
    expect(f.mock.calls[0][0]).toBe("/api/cases?status=escalated&q=pull&limit=100");
  });
});
