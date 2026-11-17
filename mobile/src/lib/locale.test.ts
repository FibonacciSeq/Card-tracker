import { describe, expect, it } from "vitest";

import {
  DEFAULT_LOCALE,
  getText,
  normalizeLocale,
  translationMap,
  type TranslationKey,
} from "./locale";

describe("locale", () => {
  it("defaults unknown locales to English", () => {
    expect(normalizeLocale("fr")).toBe(DEFAULT_LOCALE);
    expect(normalizeLocale(undefined)).toBe(DEFAULT_LOCALE);
    expect(normalizeLocale(null)).toBe(DEFAULT_LOCALE);
  });

  it("normalizes supported locales case-insensitively", () => {
    expect(normalizeLocale("SR")).toBe("sr");
  });

  it("returns the correct Serbian text", () => {
    expect(getText("sr", "homeTitle")).toBe("Pronađite kartu koju vam treba.");
    expect(getText("sr", "language")).toBe("Jezik");
  });

  it("falls back to English and then to the translation key", () => {
    const saved = translationMap.sr.homeTitle;
    delete (translationMap.sr as Partial<Record<TranslationKey, string>>).homeTitle;
    try {
      expect(getText("sr", "homeTitle")).toBe(translationMap.en.homeTitle);
    } finally {
      translationMap.sr.homeTitle = saved;
    }
    expect(getText("sr", "not-a-real-key" as TranslationKey)).toBe("not-a-real-key");
  });

  it("interpolates translation parameters", () => {
    translationMap.en.greeting = "Hello {name}, you have {count} cards.";
    try {
      expect(getText("en", "greeting", { name: "Ana", count: 2 })).toBe("Hello Ana, you have 2 cards.");
    } finally {
      delete translationMap.en.greeting;
    }
  });
});
