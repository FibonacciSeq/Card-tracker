import { describe, expect, it, vi } from "vitest";

import { clearSession, loadSession, saveSession } from "../auth/session";

const session = {
  token: "token",
  expiresAt: Date.now() + 60_000,
  me: {
    id: "u1",
    tenant_id: "t1",
    email: "owner@example.com",
    role: "owner",
    display_name: "Owner",
  },
} as Parameters<typeof saveSession>[0];

const key = "cardtracker.admin.session";

describe("admin session storage", () => {
  it("round-trips a live session", () => {
    saveSession(session);
    expect(loadSession()).toEqual(session);
    clearSession();
    expect(loadSession()).toBeNull();
  });

  it("ignores absent and malformed payloads", () => {
    expect(loadSession()).toBeNull();
    window.localStorage.setItem(key, "not-json");
    expect(loadSession()).toBeNull();
    window.localStorage.setItem(key, JSON.stringify({ token: 1 }));
    expect(loadSession()).toBeNull();
    window.localStorage.setItem(key, JSON.stringify({ token: "t", expiresAt: 1, me: null }));
    expect(loadSession()).toBeNull();
  });

  it("drops an expired session", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-29T10:00:00Z"));
    window.localStorage.setItem(
      key,
      JSON.stringify({ ...session, expiresAt: Date.now() - 1 }),
    );
    expect(loadSession()).toBeNull();
    expect(window.localStorage.getItem(key)).toBeNull();
    vi.useRealTimers();
  });
});
