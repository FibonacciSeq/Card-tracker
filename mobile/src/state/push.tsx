import * as Device from "expo-device";
import * as Notifications from "expo-notifications";
import { AndroidImportance } from "expo-notifications";
import { router, type Href } from "expo-router";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { Platform } from "react-native";

import { registerPushToken, unregisterPushToken } from "../api/client";
import { canUseNativePush, notificationTargetPath, pushPlatform } from "../lib/push";
import { useAuth } from "./auth";

export type PushStatus =
  | "idle"
  | "enabling"
  | "enabled"
  | "denied"
  | "unsupported"
  | "error";

type PushContextValue = {
  status: PushStatus;
  error: string | null;
  enable: () => Promise<void>;
  disable: () => Promise<void>;
};

const PushContext = createContext<PushContextValue | null>(null);

if (Platform.OS !== "web") {
  Notifications.setNotificationHandler({
    handleNotification: async () => ({
      shouldShowBanner: true,
      shouldShowList: true,
      shouldPlaySound: true,
      shouldSetBadge: false,
    }),
  });
}

export function PushProvider({ children }: { children: ReactNode }) {
  const { token: authToken, isAuthenticated } = useAuth();
  const [status, setStatus] = useState<PushStatus>("idle");
  const [deviceToken, setDeviceToken] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const previousAuth = useRef<string | null>(null);

  useEffect(() => {
    if (!isAuthenticated) return;
    let cancelled = false;
    void (async () => {
      if (!canUseNativePush(Platform.OS, Device.isDevice)) {
        if (!cancelled) setStatus("unsupported");
        return;
      }
      const permission = await Notifications.getPermissionsAsync();
      if (cancelled) return;
      if (permission.granted) {
        setStatus((current) => (current === "enabled" ? current : "idle"));
      } else if (permission.status === "denied") {
        setStatus("denied");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [isAuthenticated]);

  useEffect(() => {
    if (authToken) {
      previousAuth.current = authToken;
      return;
    }
    if (!deviceToken) {
      previousAuth.current = null;
      return;
    }
    const oldToken = previousAuth.current;
    previousAuth.current = null;
    if (!oldToken) {
      setDeviceToken(null);
      setStatus("idle");
      return;
    }
    void unregisterPushToken(oldToken, deviceToken)
      .catch(() => undefined)
      .finally(() => {
        setDeviceToken(null);
        setStatus("idle");
      });
  }, [authToken, deviceToken]);

  useEffect(() => {
    if (
      !authToken ||
      !deviceToken ||
      status !== "enabled" ||
      Platform.OS === "web"
    ) {
      return;
    }
    const subscription = Notifications.addPushTokenListener((next) => {
      const platform = pushPlatform(next.type);
      if (!platform || typeof next.data !== "string") return;
      void registerPushToken(authToken, { token: next.data, platform })
        .then(() => setDeviceToken(next.data))
        .catch((caught) => {
          setError(
            caught instanceof Error
              ? caught.message
              : "Could not refresh push registration.",
          );
        });
    });
    return () => subscription.remove();
  }, [authToken, deviceToken, status]);

  useEffect(() => {
    if (Platform.OS === "web") return;
    const open = (response: Notifications.NotificationResponse) => {
      const path = notificationTargetPath(response.notification.request.content.data);
      if (path) router.push(path as Href);
    };
    const subscription = Notifications.addNotificationResponseReceivedListener(open);
    void Notifications.getLastNotificationResponseAsync().then((response) => {
      if (response) open(response);
    });
    return () => subscription.remove();
  }, []);

  const enable = useCallback(async () => {
    setError(null);
    if (!authToken) {
      setStatus("idle");
      return;
    }
    if (!canUseNativePush(Platform.OS, Device.isDevice)) {
      setStatus("unsupported");
      return;
    }
    setStatus("enabling");
    try {
      if (Platform.OS === "android") {
        await Notifications.setNotificationChannelAsync("default", {
          name: "Card Tracker",
          importance: AndroidImportance.HIGH,
        });
      }
      let permission = await Notifications.getPermissionsAsync();
      if (!permission.granted) {
        permission = await Notifications.requestPermissionsAsync();
      }
      if (!permission.granted) {
        setStatus("denied");
        return;
      }
      const token = await Notifications.getDevicePushTokenAsync();
      const platform = pushPlatform(token.type);
      if (!platform || typeof token.data !== "string") {
        setStatus("unsupported");
        return;
      }
      await registerPushToken(authToken, { token: token.data, platform });
      setDeviceToken(token.data);
      setStatus("enabled");
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "Could not enable notifications.",
      );
      setStatus("error");
    }
  }, [authToken]);

  const disable = useCallback(async () => {
    setError(null);
    if (!authToken || !deviceToken) {
      setDeviceToken(null);
      setStatus("idle");
      return;
    }
    try {
      await unregisterPushToken(authToken, deviceToken);
      setDeviceToken(null);
      setStatus("idle");
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "Could not disable notifications.",
      );
      setStatus("error");
    }
  }, [authToken, deviceToken]);

  const value = useMemo<PushContextValue>(
    () => ({ status, error, enable, disable }),
    [disable, enable, error, status],
  );

  return <PushContext.Provider value={value}>{children}</PushContext.Provider>;
}

export function usePush(): PushContextValue {
  const context = useContext(PushContext);
  if (!context) throw new Error("usePush must be used inside PushProvider");
  return context;
}
