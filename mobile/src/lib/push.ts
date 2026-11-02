import { targetFromUrl, targetPath } from "./deeplink";

export type PushPlatform = "ios" | "android";

/** Native FCM/APNs only; web push is deliberately out of scope. */
export function pushPlatform(os: string): PushPlatform | null {
  return os === "ios" || os === "android" ? os : null;
}

export function canUseNativePush(os: string, isDevice: boolean): boolean {
  return isDevice && pushPlatform(os) !== null;
}

/** Converts the `url` data field on a push payload into an Expo Router path. */
export function notificationTargetPath(data: unknown): string | null {
  if (typeof data !== "object" || data === null) return null;
  const url = (data as { url?: unknown }).url;
  if (typeof url !== "string") return null;
  const target = targetFromUrl(url);
  return target ? targetPath(target) : null;
}
