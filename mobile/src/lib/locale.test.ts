import { describe, expect, it } from "vitest";

import { DEFAULT_LOCALE, getText, normalizeLocale, translationMap } from "./locale";

describe("mobile locale (English only)", () => {
  it("always normalizes to English", () => {
    expect(DEFAULT_LOCALE).toBe("en");
    expect(normalizeLocale("sr")).toBe("en");
    expect(normalizeLocale("it")).toBe("en");
    expect(normalizeLocale(undefined)).toBe("en");
    expect(normalizeLocale(null)).toBe("en");
  });

  it("returns English text or the key itself", () => {
    expect(getText("en", "homeTitle")).toBe("Find the card you need.");
    expect(getText("en", "language")).toBe("Language");
    expect(getText("en", "not-a-real-key")).toBe("not-a-real-key");
  });

  it("interpolates translation parameters", () => {
    translationMap.en.greeting = "Hello {name}, you have {count} cards ({missing}).";
    try {
      expect(getText("en", "greeting", { name: "Ana", count: 2 })).toBe(
        "Hello Ana, you have 2 cards ({missing}).",
      );
    } finally {
      delete translationMap.en.greeting;
    }
  });
});
