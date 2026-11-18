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
    expect(normalizeLocale("it")).toBe(DEFAULT_LOCALE);
    expect(normalizeLocale(undefined)).toBe(DEFAULT_LOCALE);
    expect(normalizeLocale(null)).toBe(DEFAULT_LOCALE);
  });

  it("normalizes supported locales case-insensitively", () => {
    expect(normalizeLocale("SR")).toBe("sr");
    expect(normalizeLocale("RU")).toBe("ru");
    expect(normalizeLocale("ES")).toBe("es");
    expect(normalizeLocale("FR")).toBe("fr");
    expect(normalizeLocale("DE")).toBe("de");
  });

  it("returns translated text for every supported language", () => {
    expect(getText("sr", "homeTitle")).toBe("Pronađite kartu koju vam treba.");
    expect(getText("sr", "language")).toBe("Jezik");
    expect(getText("ru", "homeTitle")).toBe("Найдите нужную карту.");
    expect(getText("es", "homeTitle")).toBe("Encuentra la carta que necesitas.");
    expect(getText("fr", "homeTitle")).toBe("Trouvez la carte qu'il vous faut.");
    expect(getText("de", "homeTitle")).toBe("Finde die Karte, die du brauchst.");
    expect(getText("en", "homeTitle")).toBe("Find the card you need.");
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
