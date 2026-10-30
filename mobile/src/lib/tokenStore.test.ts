import { beforeEach, describe, expect, it, vi } from "vitest";

import { readGuestToken, removeGuestToken, writeGuestToken } from "./tokenStore";

const { platform, storage, asyncStorage, secureStore } = vi.hoisted(() => {
  const platform = { OS: "web" };
  const storage = new Map<string, string>();
  const asyncStorage = {
    setItem: vi.fn(async (key: string, value: string) => {
      storage.set(key, value);
    }),
    getItem: vi.fn(async (key: string) => storage.get(key) ?? null),
    removeItem: vi.fn(async (key: string) => {
      storage.delete(key);
    }),
  };
  const secureStore = {
    setItemAsync: vi.fn(async (key: string, value: string) => {
      storage.set(key, value);
    }),
    getItemAsync: vi.fn(async (key: string) => storage.get(key) ?? null),
    deleteItemAsync: vi.fn(async (key: string) => {
      storage.delete(key);
    }),
  };
  return { platform, storage, asyncStorage, secureStore };
});

vi.mock("react-native", () => ({ Platform: platform }));
vi.mock("@react-native-async-storage/async-storage", () => ({ default: asyncStorage }));
vi.mock("expo-secure-store", () => secureStore);

describe("guest token storage", () => {
  beforeEach(() => {
    storage.clear();
    vi.clearAllMocks();
    platform.OS = "web";
  });

  it("uses AsyncStorage on web", async () => {
    await writeGuestToken("key", "token");
    expect(asyncStorage.setItem).toHaveBeenCalledWith("key", "token");
    await expect(readGuestToken("key")).resolves.toBe("token");
    await removeGuestToken("key");
    expect(asyncStorage.removeItem).toHaveBeenCalledWith("key");
    await expect(readGuestToken("key")).resolves.toBeNull();
  });

  it("uses SecureStore on native platforms", async () => {
    platform.OS = "ios";
    await writeGuestToken("key", "token");
    expect(secureStore.setItemAsync).toHaveBeenCalledWith("key", "token");
    await expect(readGuestToken("key")).resolves.toBe("token");
    await removeGuestToken("key");
    expect(secureStore.deleteItemAsync).toHaveBeenCalledWith("key");
    await expect(readGuestToken("key")).resolves.toBeNull();
  });
});
