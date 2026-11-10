import Constants from "expo-constants";
import { Platform } from "react-native";

function inferHost(): string {
  const hostUri = Constants.expoConfig?.hostUri;
  if (hostUri) {
    const host = hostUri.split(":")[0];
    if (host) return host;
  }
  if (Platform.OS === "android") return "10.0.2.2";
  return "127.0.0.1";
}

/**
 * VS Code port forwarding serves the web app from
 * `https://{tunnelId}-{port}.{region}.devtunnels.ms`, and every port forwarded
 * from the same window shares the tunnel id. When the app is opened through
 * such a URL the API tunnel is the same host with the port segment swapped to
 * 8000. Without this the app on a forwarded URL keeps calling the developer's
 * LAN address, which the remote browser cannot reach.
 */
function forwardedApiUrl(): string | null {
  if (Platform.OS !== "web" || typeof window === "undefined") return null;
  const match = /^(.+)-\d+\.((?:[a-z0-9-]+\.)*devtunnels\.ms)$/i.exec(
    window.location.hostname,
  );
  return match ? `https://${match[1]}-8000.${match[2]}` : null;
}

const explicit = process.env.EXPO_PUBLIC_API_BASE_URL?.trim();

export const API_BASE_URL = (
  explicit || forwardedApiUrl() || `http://${inferHost()}:8000`
).replace(/\/$/, "");

export function shopPath(slug: string): string {
  return `/shop/${encodeURIComponent(slug)}`;
}
