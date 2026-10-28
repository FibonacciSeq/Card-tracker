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

const explicit = process.env.EXPO_PUBLIC_API_BASE_URL?.trim();

export const API_BASE_URL = (explicit || `http://${inferHost()}:8000`).replace(/\/$/, "");

export function shopPath(slug: string): string {
  return `/shop/${encodeURIComponent(slug)}`;
}
