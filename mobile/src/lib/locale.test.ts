import { describe, expect, it } from "vitest";

import { DEFAULT_LOCALE, getText, normalizeLocale } from "./locale";

describe("locale", () => {
  it("defaults unknown locales to English", () => {
    expect(normalizeLocale("fr")).toBe(DEFAULT_LOCALE);
  });

  it("returns the correct Serbian text", () => {
    expect(getText("sr", "homeTitle")).toBe("Pronađite kartu koju vam treba.");
    expect(getText("sr", "language")).toBe("Jezik");
  });
});
