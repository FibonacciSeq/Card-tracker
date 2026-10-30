import { describe, expect, it } from "vitest";

import { formatDateTime, formatMoney, formatRemaining, statusTone, titleCase } from "./format";

describe("mobile formatting", () => {
  it("formats missing and valid money", () => {
    expect(formatMoney(null)).toBe("—");
    expect(formatMoney(undefined)).toBe("—");
    expect(formatMoney({ amount_minor: 125050, currency: "RSD" })).toMatch(/1[.,]?250[.,]50/);
  });

  it("falls back when the currency is unknown", () => {
    expect(formatMoney({ amount_minor: 1000, currency: "NOTACURRENCY" })).toBe("NOTACURRENCY 10.00");
  });

  it("formats valid and invalid dates", () => {
    expect(formatDateTime("not-a-date")).toBe("not-a-date");
    expect(formatDateTime("2026-10-29T10:30:00Z")).toBeTruthy();
  });

  it("describes remaining time at every scale", () => {
    const now = Date.parse("2026-10-29T10:00:00Z");
    expect(formatRemaining("bad", now)).toBe("");
    expect(formatRemaining("2026-10-29T09:59:00Z", now)).toBe("Expired");
    expect(formatRemaining("2026-10-29T10:20:00Z", now)).toBe("20 min");
    expect(formatRemaining("2026-10-29T13:05:00Z", now)).toBe("3 h 5 min");
    expect(formatRemaining("2026-11-01T10:00:00Z", now)).toBe("3 days");
  });

  it("title-cases status values", () => {
    expect(titleCase("WAITING_FOR_CARDS")).toBe("Waiting For Cards");
  });

  it("maps every status tone", () => {
    expect(statusTone("READY")).toBe("success");
    expect(statusTone("REQUESTED")).toBe("accent");
    expect(statusTone("CONFIRMED")).toBe("accent");
    expect(statusTone("QUOTED")).toBe("accent");
    expect(statusTone("ACCEPTED")).toBe("success");
    expect(statusTone("CONVERTED")).toBe("success");
    expect(statusTone("CANCELLED")).toBe("danger");
    expect(statusTone("EXPIRED")).toBe("danger");
    expect(statusTone("DECLINED")).toBe("danger");
    expect(statusTone("UNKNOWN")).toBe("muted");
  });
});
