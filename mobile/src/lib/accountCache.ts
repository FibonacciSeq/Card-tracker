import type { QueryClient } from "@tanstack/react-query";

import { persistQueryCache } from "./queryCache";

/**
 * Every request-scoped account query lives under this root. Guest tokens,
 * public shop data, and device-local guest stores deliberately do not.
 */
export const ACCOUNT_QUERY_ROOT = "account";

/**
 * Remove cached account data after an identity change and rewrite the persisted
 * snapshot immediately. Guest data and the device-local cart are not touched.
 */
export async function clearAccountCache(client: QueryClient): Promise<void> {
  try {
    await client.cancelQueries({ queryKey: [ACCOUNT_QUERY_ROOT] });
  } catch {
    // Cancellation is best-effort. Removing the queries still hides stale data.
  }
  client.removeQueries({ queryKey: [ACCOUNT_QUERY_ROOT] });
  await persistQueryCache(client);
}
