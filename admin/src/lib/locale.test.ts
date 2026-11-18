import { describe, expect, it } from "vitest";

import {
  DEFAULT_LOCALE,
  getText,
  normalizeLocale,
  translationMap,
  type TranslationKey,
} from "./locale";

describe("admin locale", () => {
  it("defaults unknown locales to English", () => {
    expect(normalizeLocale("it")).toBe(DEFAULT_LOCALE);
    expect(normalizeLocale(undefined)).toBe(DEFAULT_LOCALE);
    expect(normalizeLocale(null)).toBe(DEFAULT_LOCALE);
  });

  it("normalizes supported locales case-insensitively", () => {
    expect(normalizeLocale("RU")).toBe("ru");
    expect(normalizeLocale("ES")).toBe("es");
    expect(normalizeLocale("FR")).toBe("fr");
    expect(normalizeLocale("DE")).toBe("de");
    expect(normalizeLocale("SR")).toBe("sr");
    expect(normalizeLocale("EN")).toBe("en");
  });

  it("returns translated navigation text for every supported language", () => {
    expect(getText("en", "Dashboard")).toBe("Dashboard");
    expect(getText("ru", "Dashboard")).toBe("Панель");
    expect(getText("es", "Dashboard")).toBe("Panel");
    expect(getText("fr", "Dashboard")).toBe("Tableau de bord");
    expect(getText("de", "Dashboard")).toBe("Übersicht");
    expect(getText("sr", "Dashboard")).toBe("Pregled");
    expect(getText("de", "language")).toBe("Sprache");
  });

  it("falls back to English and then to the translation key", () => {
    const saved = translationMap.sr.Dashboard as string;
    delete (translationMap.sr as Partial<Record<TranslationKey, string>>).Dashboard;
    try {
      expect(getText("sr", "Dashboard")).toBe(translationMap.en.Dashboard);
    } finally {
      translationMap.sr.Dashboard = saved;
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
