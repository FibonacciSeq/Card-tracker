import { afterEach, describe, expect, it, vi } from "vitest";

const constants = { expoConfig: { hostUri: undefined as string | undefined } };
const platform = { OS: "ios" };

vi.mock("expo-constants", () => ({ default: constants }));
vi.mock("react-native", () => ({ Platform: platform }));

async function load() {
  vi.resetModules();
  return import("./config");
}

describe("mobile API config", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
    constants.expoConfig.hostUri = undefined;
    platform.OS = "ios";
  });

  it("prefers an explicit base URL and trims a trailing slash", async () => {
    vi.stubEnv("EXPO_PUBLIC_API_BASE_URL", " https://cards.example/ ");
    const config = await load();
    expect(config.API_BASE_URL).toBe("https://cards.example");
    expect(config.shopPath("bolt shop")).toBe("/shop/bolt%20shop");
  });

  it("uses the Expo host", async () => {
    constants.expoConfig.hostUri = "192.168.1.5:8081";
    const config = await load();
    expect(config.API_BASE_URL).toBe("http://192.168.1.5:8000");
  });

  it("falls back to the Android host", async () => {
    platform.OS = "android";
    const config = await load();
    expect(config.API_BASE_URL).toBe("http://10.0.2.2:8000");
  });

  it("falls back to localhost elsewhere", async () => {
    platform.OS = "web";
    const config = await load();
    expect(config.API_BASE_URL).toBe("http://127.0.0.1:8000");
  });

  it("ignores an empty host segment", async () => {
    constants.expoConfig.hostUri = ":8081";
    const config = await load();
    expect(config.API_BASE_URL).toBe("http://127.0.0.1:8000");
  });

  it("uses the API tunnel when the web app is behind VS Code port forwarding", async () => {
    platform.OS = "web";
    constants.expoConfig.hostUri = "127.0.0.1:8081";
    vi.stubGlobal("window", { location: { hostname: "l3rs99qw-8081.usw2.devtunnels.ms" } });
    const config = await load();
    expect(config.API_BASE_URL).toBe("https://l3rs99qw-8000.usw2.devtunnels.ms");
  });

  it("handles dev tunnel hosts without a region label", async () => {
    platform.OS = "web";
    vi.stubGlobal("window", { location: { hostname: "d4chrl5d-8081.devtunnels.ms" } });
    const config = await load();
    expect(config.API_BASE_URL).toBe("https://d4chrl5d-8000.devtunnels.ms");
  });

  it("ignores web hosts that are not dev tunnels", async () => {
    platform.OS = "web";
    vi.stubGlobal("window", { location: { hostname: "localhost" } });
    const config = await load();
    expect(config.API_BASE_URL).toBe("http://127.0.0.1:8000");
  });

  it("ignores the dev tunnel host on native platforms", async () => {
    vi.stubGlobal("window", { location: { hostname: "l3rs99qw-8081.usw2.devtunnels.ms" } });
    const config = await load();
    expect(config.API_BASE_URL).toBe("http://127.0.0.1:8000");
  });

  it("prefers an explicit base URL over the dev tunnel host", async () => {
    platform.OS = "web";
    vi.stubGlobal("window", { location: { hostname: "l3rs99qw-8081.usw2.devtunnels.ms" } });
    vi.stubEnv("EXPO_PUBLIC_API_BASE_URL", "https://cards.example");
    const config = await load();
    expect(config.API_BASE_URL).toBe("https://cards.example");
  });
});
