import { describe, expect, it, vi } from "vitest";

import { describeRemaining, formatDateTime, formatMoney, percent } from "./format";

describe("format helpers", () => {
  it("formats money and dates", () => {
    expect(formatMoney(125050, "RSD")).toMatch(/1[.,]250[.,]50/);
    expect(formatDateTime("2026-10-29T10:30:00Z")).toBeTruthy();
    expect(formatDateTime(new Date("2026-10-29T10:30:00Z"))).toBeTruthy();
  });

  it("describes a future hold with hours and minutes", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-29T10:00:00Z"));
    expect(describeRemaining("2026-10-29T12:30:00Z")).toEqual({
      label: "2h 30m left",
      overdue: false,
    });
    vi.useRealTimers();
  });

  it("describes a short future hold in minutes", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-29T10:00:00Z"));
    expect(describeRemaining("2026-10-29T10:05:00Z")).toEqual({
      label: "5m left",
      overdue: false,
    });
    vi.useRealTimers();
  });

  it("never labels a future hold as zero minutes", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-29T10:00:00Z"));
    expect(describeRemaining("2026-10-29T10:00:01Z").label).toBe("1m left");
    vi.useRealTimers();
  });

  it("describes overdue holds", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-29T10:00:00Z"));
    expect(describeRemaining("2026-10-29T09:30:00Z")).toEqual({
      label: "expired 30m ago",
      overdue: true,
    });
    vi.useRealTimers();
  });

  it("calculates a bounded percentage", () => {
    expect(percent(1, 4)).toBe(25);
    expect(percent(1, 0)).toBe(0);
    expect(percent(1, -2)).toBe(0);
  });
});
