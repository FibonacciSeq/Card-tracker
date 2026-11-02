import { describe, expect, it } from "vitest";

import { cardDeepLink, shopDeepLink } from "./deeplink";
import { canUseNativePush, notificationTargetPath, pushPlatform } from "./push";

describe("pushPlatform", () => {
  it("accepts the two native platforms", () => {
    expect(pushPlatform("ios")).toBe("ios");
    expect(pushPlatform("android")).toBe("android");
  });

  it("rejects web and unknown platforms", () => {
    expect(pushPlatform("web")).toBeNull();
    expect(pushPlatform("windows")).toBeNull();
  });
});

describe("canUseNativePush", () => {
  it("requires a physical native device", () => {
    expect(canUseNativePush("ios", true)).toBe(true);
    expect(canUseNativePush("android", true)).toBe(true);
    expect(canUseNativePush("ios", false)).toBe(false);
    expect(canUseNativePush("web", true)).toBe(false);
  });
});

describe("notificationTargetPath", () => {
  it("maps shop and card deep links to router paths", () => {
    expect(notificationTargetPath({ url: shopDeepLink("bolt-shop") })).toBe(
      "/shop/bolt-shop",
    );
    expect(
      notificationTargetPath({
        url: cardDeepLink("bolt-shop", "11111111-1111-1111-1111-111111111111"),
      }),
    ).toBe("/shop/bolt-shop/card/11111111-1111-1111-1111-111111111111");
  });

  it("ignores malformed payloads and foreign links", () => {
    expect(notificationTargetPath(null)).toBeNull();
    expect(notificationTargetPath("cardtracker://shop/bolt-shop")).toBeNull();
    expect(notificationTargetPath({})).toBeNull();
    expect(notificationTargetPath({ url: 42 })).toBeNull();
    expect(notificationTargetPath({ url: "https://example.com/elsewhere" })).toBeNull();
  });
});
