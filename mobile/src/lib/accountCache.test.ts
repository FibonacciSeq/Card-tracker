import { QueryClient } from "@tanstack/react-query";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ACCOUNT_QUERY_ROOT, clearAccountCache } from "./accountCache";
import { QUERY_CACHE_STORAGE_KEY } from "./queryCache";

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

describe("accountCache", () => {
  beforeEach(async () => {
    await AsyncStorage.clear();
    vi.clearAllMocks();
  });

  it("removes every account-scoped query and rewrites the stored snapshot", async () => {
    const client = new QueryClient();
    client.setQueryData([ACCOUNT_QUERY_ROOT], { stale: true });
    client.setQueryData([ACCOUNT_QUERY_ROOT, "reservations"], { items: [] });
    client.setQueryData(["shops", ""], [{ slug: "bolt-shop" }]);

    await clearAccountCache(client);

    expect(client.getQueryData([ACCOUNT_QUERY_ROOT])).toBeUndefined();
    expect(client.getQueryData([ACCOUNT_QUERY_ROOT, "reservations"])).toBeUndefined();
    expect(client.getQueryData(["shops", ""])).toEqual([{ slug: "bolt-shop" }]);

    const persisted = JSON.parse((await AsyncStorage.getItem(QUERY_CACHE_STORAGE_KEY)) ?? "{}");
    expect(Object.keys(persisted)).toEqual([JSON.stringify(["shops", ""])]);
  });

  it("does not match similar query roots", async () => {
    const client = new QueryClient();
    client.setQueryData(["accounts", "reservations"], [{ id: "public-ish" }]);

    await clearAccountCache(client);

    expect(client.getQueryData(["accounts", "reservations"])).toEqual([{ id: "public-ish" }]);
  });

  it("still removes account queries when cancellation fails", async () => {
    const client = new QueryClient();
    client.setQueryData([ACCOUNT_QUERY_ROOT, "card-requests"], { items: [] });
    vi.spyOn(client, "cancelQueries").mockRejectedValueOnce(new Error("cancel failed"));

    await expect(clearAccountCache(client)).resolves.toBeUndefined();

    expect(client.getQueryData([ACCOUNT_QUERY_ROOT, "card-requests"])).toBeUndefined();
  });

  it("removes the persisted snapshot when only account data was cached", async () => {
    const client = new QueryClient();
    client.setQueryData([ACCOUNT_QUERY_ROOT, "restock-alerts"], { items: [] });

    await clearAccountCache(client);

    await expect(AsyncStorage.getItem(QUERY_CACHE_STORAGE_KEY)).resolves.toBeNull();
  });
});
