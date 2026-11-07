import { QueryClient } from "@tanstack/react-query";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { hydrateQueryClient, persistQueryCache, QUERY_CACHE_STORAGE_KEY } from "./queryCache";

vi.mock("@react-native-async-storage/async-storage", () => {
  const store: Record<string, string> = {};

  return {
    default: {
      getItem: vi.fn(async (key: string) => store[key] ?? null),
      setItem: vi.fn(async (key: string, value: string) => {
        store[key] = value;
      }),
      removeItem: vi.fn(async (key: string) => {
        delete store[key];
      }),
      clear: vi.fn(async () => {
        Object.keys(store).forEach((key) => delete store[key]);
      }),
    },
  };
});

describe("queryCache", () => {
  beforeEach(async () => {
    await AsyncStorage.clear();
  });

  it("persists and restores cached query data", async () => {
    const client = new QueryClient();
    client.setQueryData(["shops", ""], [{ id: "shop-1", name: "Bolt Shop" }]);

    await persistQueryCache(client);

    const restored = new QueryClient();
    await hydrateQueryClient(restored);

    expect(restored.getQueryData(["shops", ""])).toEqual([
      { id: "shop-1", name: "Bolt Shop" },
    ]);
  });

  it("ignores malformed cached payloads", async () => {
    await AsyncStorage.setItem(QUERY_CACHE_STORAGE_KEY, "{not-json");

    const client = new QueryClient();
    await hydrateQueryClient(client);

    expect(client.getQueryCache().findAll()).toHaveLength(0);
  });

  it("clears stored data when there is nothing to persist", async () => {
    await AsyncStorage.setItem(QUERY_CACHE_STORAGE_KEY, "{}");

    await persistQueryCache(new QueryClient());

    await expect(AsyncStorage.getItem(QUERY_CACHE_STORAGE_KEY)).resolves.toBeNull();
  });

  it("does nothing when there is no stored cache", async () => {
    const client = new QueryClient();

    await hydrateQueryClient(client);

    expect(client.getQueryCache().findAll()).toHaveLength(0);
  });

  it("serializes writes so the newest snapshot wins", async () => {
    const client = new QueryClient();
    client.setQueryData(["shops", ""], ["cached"]);
    let release!: () => void;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    vi.mocked(AsyncStorage.setItem).mockImplementationOnce(async () => {
      await gate;
    });

    const first = persistQueryCache(client);
    client.setQueryData(["shops", ""], ["fresh"]);
    const second = persistQueryCache(client);
    release();
    await Promise.all([first, second]);

    const raw = await AsyncStorage.getItem(QUERY_CACHE_STORAGE_KEY);
    expect(JSON.parse(raw ?? "{}")[JSON.stringify(["shops", ""])]).toEqual(["fresh"]);
  });

  it("keeps the write queue usable after a storage failure", async () => {
    const client = new QueryClient();
    client.setQueryData(["shops", ""], ["cached"]);
    vi.mocked(AsyncStorage.setItem).mockRejectedValueOnce(new Error("disk full"));

    await expect(persistQueryCache(client)).resolves.toBeUndefined();

    client.setQueryData(["shops", ""], ["fresh"]);
    await persistQueryCache(client);

    const raw = await AsyncStorage.getItem(QUERY_CACHE_STORAGE_KEY);
    expect(JSON.parse(raw ?? "{}")[JSON.stringify(["shops", ""])]).toEqual(["fresh"]);
  });

  it("ignores non-object payloads and non-array query keys", async () => {
    const client = new QueryClient();

    await AsyncStorage.setItem(QUERY_CACHE_STORAGE_KEY, "[]");
    await hydrateQueryClient(client);
    expect(client.getQueryCache().findAll()).toHaveLength(0);

    await AsyncStorage.setItem(
      QUERY_CACHE_STORAGE_KEY,
      JSON.stringify({ [JSON.stringify("not-an-array")]: { value: 1 }, broken: { value: 2 } }),
    );
    await hydrateQueryClient(client);
    expect(client.getQueryCache().findAll()).toHaveLength(0);
  });
});
