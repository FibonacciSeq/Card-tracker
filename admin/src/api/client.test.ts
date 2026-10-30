import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, request, requestBlob, setAccessToken } from "./client";

function response(body: string, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    text: async () => body,
    blob: async () => new Blob([body]),
  } as Response;
}

describe("API client", () => {
  beforeEach(() => {
    setAccessToken(null);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("sends JSON, bearer auth, and parses JSON", async () => {
    setAccessToken("token");
    const fetchMock = vi.fn().mockResolvedValue(response('{"ok":true}'));
    vi.stubGlobal("fetch", fetchMock);

    await expect(request("/x", { method: "POST", body: { a: 1 } })).resolves.toEqual({ ok: true });
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe("/x");
    expect(init.headers.Authorization).toBe("Bearer token");
    expect(init.headers["Content-Type"]).toBe("application/json");
    expect(init.body).toBe('{"a":1}');
  });

  it("sends FormData without a JSON content type and handles empty/text bodies", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(response("", 204))
      .mockResolvedValueOnce(response("plain"));
    vi.stubGlobal("fetch", fetchMock);

    const form = new FormData();
    await expect(request("/empty", { body: form })).resolves.toBeNull();
    await expect(request("/text")).resolves.toBe("plain");

    const init = fetchMock.mock.calls[0]![1]!;
    expect(init.headers["Content-Type"]).toBeUndefined();
    expect(init.body).toBe(form);
  });

  it("dispatches an unauthorized event for a token-bearing 401", async () => {
    setAccessToken("token");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response("", 401)));
    const listener = vi.fn();
    window.addEventListener("cardtracker:unauthorized", listener);

    await expect(request("/x")).rejects.toBeInstanceOf(ApiError);
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it("formats string, validation, and status errors", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(response('{"detail":"nope"}', 400))
      .mockResolvedValueOnce(response('{"detail":[{"loc":["body","email"],"msg":"bad"}]}', 422))
      .mockResolvedValueOnce(response("", 403))
      .mockResolvedValueOnce(response("", 404))
      .mockResolvedValueOnce(response("", 500));
    vi.stubGlobal("fetch", fetchMock);

    await expect(request("/a")).rejects.toMatchObject({ message: "nope", status: 400 });
    await expect(request("/b")).rejects.toMatchObject({ message: "email: bad" });
    await expect(request("/c")).rejects.toMatchObject({ message: "You do not have permission to do that." });
    await expect(request("/d")).rejects.toMatchObject({ message: "That item no longer exists." });
    await expect(request("/e")).rejects.toMatchObject({ message: "Request failed (500)." });
  });

  it("falls back for empty validation detail arrays and entries without messages", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(response('{"detail":[]}', 400))
      .mockResolvedValueOnce(response('{"detail":[{"loc":["body"]}]}', 400));
    vi.stubGlobal("fetch", fetchMock);

    await expect(request("/empty-detail")).rejects.toMatchObject({ message: "Request failed (400)." });
    await expect(request("/no-msg")).rejects.toMatchObject({ message: "Request failed (400)." });
  });

  it("accepts validation details without a location", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(response('{"detail":[{"msg":"bad"}]}', 422)),
    );
    await expect(request("/x")).rejects.toMatchObject({ message: "bad" });
  });

  it("uses status fallbacks for an empty 401 without a token", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response("", 401)));
    await expect(request("/x")).rejects.toMatchObject({
      message: "Your session has expired. Please sign in again.",
    });
  });

  it("downloads blobs and reports blob errors", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(response("csv"))
      .mockResolvedValueOnce(response("bad", 400))
      .mockResolvedValueOnce(response("", 401));
    vi.stubGlobal("fetch", fetchMock);
    setAccessToken("token");

    const blob = await requestBlob("/export");
    expect(blob).toBeInstanceOf(Blob);
    expect(blob.size).toBe(3);
    await expect(requestBlob("/broken")).rejects.toMatchObject({ message: "Request failed (400)." });
    await expect(requestBlob("/expired")).rejects.toMatchObject({ status: 401 });
  });
});
