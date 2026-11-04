import { describe, expect, it } from "vitest";

import {
  cardDeepLink,
  cardPublicUrl,
  publicAppBaseUrl,
  shopDeepLink,
  shopPublicUrl,
  targetFromInput,
  targetFromPath,
  targetFromUrl,
  targetPath,
} from "./deeplink";

const stockId = "123e4567-e89b-12d3-a456-426614174000";

describe("QR/deep-link parsing", () => {
  it("parses shop and card paths", () => {
    expect(targetFromPath("/shop/bolt")).toEqual({ kind: "shop", slug: "bolt" });
    expect(targetFromPath("/shop/bolt/card/" + stockId)).toEqual({
      kind: "card",
      slug: "bolt",
      stockId,
    });
    expect(targetFromPath("/shop/bolt?ref=qr")).toEqual({ kind: "shop", slug: "bolt" });
    expect(targetFromPath("/shop/bolt/card/" + stockId + "#top")).toEqual({
      kind: "card",
      slug: "bolt",
      stockId,
    });
  });

  it("rejects malformed paths", () => {
    expect(targetFromPath("/other/bolt")).toBeNull();
    expect(targetFromPath("/shop")).toBeNull();
    expect(targetFromPath("/shop/-bad")).toBeNull();
    expect(targetFromPath("/shop/bolt/card")).toBeNull();
    expect(targetFromPath("/shop/bolt/card/not-a-uuid")).toBeNull();
    expect(targetFromPath("/shop/bolt/unknown")).toBeNull();
  });

  it("decodes percent-encoded segments and survives broken encoding", () => {
    expect(targetFromPath("/shop/bolt%2Dshop")).toEqual({ kind: "shop", slug: "bolt-shop" });
    expect(targetFromPath("/shop/%E0%A4%A")).toBeNull();
  });

  it("parses custom, web, and Expo links", () => {
    expect(targetFromUrl("cardtracker://shop/bolt")).toEqual({ kind: "shop", slug: "bolt" });
    expect(targetFromUrl("https://example.test/shop/bolt")).toEqual({ kind: "shop", slug: "bolt" });
    expect(targetFromUrl("exp://127.0.0.1:8081/--/shop/bolt/card/" + stockId)).toEqual({
      kind: "card",
      slug: "bolt",
      stockId,
    });
    expect(targetFromUrl("/shop/bolt")).toEqual({ kind: "shop", slug: "bolt" });
  });

  it("rejects empty, long, foreign, and malformed URLs", () => {
    expect(targetFromUrl("")).toBeNull();
    expect(targetFromUrl("x".repeat(2049))).toBeNull();
    expect(targetFromUrl("ftp://example.test/shop/bolt")).toBeNull();
    expect(targetFromUrl("https://[bad")).toBeNull();
  });

  it("accepts typed slugs but not arbitrary text", () => {
    expect(targetFromInput("bolt-shop")).toEqual({ kind: "shop", slug: "bolt-shop" });
    expect(targetFromInput("  cardtracker://shop/bolt  ")).toEqual({ kind: "shop", slug: "bolt" });
    expect(targetFromInput("not a slug")).toBeNull();
    expect(targetFromInput("")).toBeNull();
    expect(targetFromInput("x".repeat(2049))).toBeNull();
  });

  it("renders canonical paths and links", () => {
    expect(targetPath({ kind: "shop", slug: "bolt shop" })).toBe("/shop/bolt%20shop");
    expect(targetPath({ kind: "card", slug: "bolt", stockId })).toBe(`/shop/bolt/card/${stockId}`);
    expect(shopPublicUrl("bolt shop")).toBe("https://app.cardtracker.local/shop/bolt%20shop");
    expect(cardPublicUrl("bolt", stockId)).toBe(`https://app.cardtracker.local/shop/bolt/card/${stockId}`);
    expect(shopDeepLink("bolt shop")).toBe("cardtracker://shop/bolt%20shop");
    expect(cardDeepLink("bolt", stockId)).toBe(`cardtracker://shop/bolt/card/${stockId}`);
  });

  it("falls back when the configured public app URL is blank", () => {
    const previousBase = process.env.EXPO_PUBLIC_APP_BASE_URL;
    process.env.EXPO_PUBLIC_APP_BASE_URL = "   ";
    try {
      expect(publicAppBaseUrl()).toBe("https://app.cardtracker.local");
    } finally {
      if (previousBase === undefined) {
        delete process.env.EXPO_PUBLIC_APP_BASE_URL;
      } else {
        process.env.EXPO_PUBLIC_APP_BASE_URL = previousBase;
      }
    }
  });
});
