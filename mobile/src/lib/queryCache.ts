import AsyncStorage from "@react-native-async-storage/async-storage";
import type { QueryClient } from "@tanstack/react-query";

export const QUERY_CACHE_STORAGE_KEY = "cardtracker.react-query-cache.v1";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isSerializableQueryKey(value: unknown): value is unknown[] {
  return Array.isArray(value);
}

export async function persistQueryCache(client: QueryClient): Promise<void> {
  const snapshot = Object.fromEntries(
    client
      .getQueryCache()
      .findAll()
      .filter((query) => typeof query.state.data !== "undefined")
      .map((query) => [JSON.stringify(query.queryKey), query.state.data]),
  );

  if (Object.keys(snapshot).length === 0) {
    await AsyncStorage.removeItem(QUERY_CACHE_STORAGE_KEY);
    return;
  }

  await AsyncStorage.setItem(QUERY_CACHE_STORAGE_KEY, JSON.stringify(snapshot));
}

export async function hydrateQueryClient(client: QueryClient): Promise<void> {
  const raw = await AsyncStorage.getItem(QUERY_CACHE_STORAGE_KEY);
  if (!raw) return;

  try {
    const parsed = JSON.parse(raw);
    if (!isRecord(parsed)) return;

    for (const [key, data] of Object.entries(parsed)) {
      try {
        const queryKey = JSON.parse(key);
        if (!isSerializableQueryKey(queryKey)) continue;
        client.setQueryData(queryKey, data);
      } catch {
        // Ignore malformed cached entries.
      }
    }
  } catch {
    // Ignore malformed cache payloads.
  }
}
