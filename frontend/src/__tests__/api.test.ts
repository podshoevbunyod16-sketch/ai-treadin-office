import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, buildUrl, errorMessage, getToken, setToken } from "../api";

afterEach(() => {
  vi.restoreAllMocks();
  setToken(null);
});

describe("api helpers", () => {
  it("builds query strings skipping empty values", () => {
    expect(buildUrl("/api/x", { a: 1, b: "", c: null, d: "q w" })).toBe("/api/x?a=1&d=q+w");
    expect(buildUrl("/api/x")).toBe("/api/x");
  });

  it("formats FastAPI validation errors", () => {
    const detail = [{ loc: ["body", "volume"], msg: "Input should be greater than 0" }];
    expect(errorMessage(detail, "x")).toBe("volume: Input should be greater than 0");
    expect(errorMessage("plain", "x")).toBe("plain");
    expect(errorMessage(undefined, "fallback")).toBe("fallback");
  });

  it("sends bearer token and parses JSON", async () => {
    setToken("tok123");
    const f = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }));
    const r = await api("/api/health");
    expect(r).toEqual({ ok: true });
    const init = f.mock.calls[0][1] as RequestInit;
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer tok123");
  });

  it("clears token and emits logout on 401", async () => {
    setToken("expired");
    const onLogout = vi.fn();
    window.addEventListener("ato:logout", onLogout);
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ detail: "Сессия истекла" }), { status: 401 }));
    await expect(api("/api/accounts")).rejects.toBeInstanceOf(ApiError);
    expect(getToken()).toBeNull();
    expect(onLogout).toHaveBeenCalled();
  });

  it("reports network errors honestly", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));
    await expect(api("/api/x")).rejects.toThrow("Сервер недоступен");
  });
});
