import { describe, expect, it } from "vitest";

import { formatDistanceKm, SHOP_RADIUS_OPTIONS } from "./geo";

describe("shop distance formatting", () => {
  it("shows short distances in metres rounded to ten metres", () => {
    expect(formatDistanceKm(0)).toBe("10 m");
    expect(formatDistanceKm(0.034)).toBe("30 m");
    expect(formatDistanceKm(0.847)).toBe("850 m");
  });

  it("promotes a near-kilometre distance instead of showing 1000 m", () => {
    expect(formatDistanceKm(0.999)).toBe("1.0 km");
  });

  it("keeps one decimal below ten kilometres and rounds above", () => {
    expect(formatDistanceKm(1.24)).toBe("1.2 km");
    expect(formatDistanceKm(9.94)).toBe("9.9 km");
    expect(formatDistanceKm(12.6)).toBe("13 km");
  });

  it("returns an empty label for invalid distances", () => {
    expect(formatDistanceKm(Number.NaN)).toBe("");
    expect(formatDistanceKm(-1)).toBe("");
  });

  it("offers a small fixed set of radius choices", () => {
    expect(SHOP_RADIUS_OPTIONS).toEqual([5, 10, 25, 50]);
  });
});
