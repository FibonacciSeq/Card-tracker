import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { useMyNotifications, useMyPushTokens } from "../api/queries";
import type { AccountNotification, PushToken } from "../api/types";
import { EmptyState } from "../components/EmptyState";
import { ErrorState, LoadingState } from "../components/LoadingState";
import { PrimaryButton } from "../components/PrimaryButton";
import { formatDateTime } from "../lib/format";
import { useAuth } from "../state/auth";
import { colors, radii, spacing, type } from "../theme";

const statusColors: Record<AccountNotification["status"], string> = {
  pending: colors.inkMuted,
  retrying: colors.accent,
  sent: colors.success,
  skipped: colors.inkMuted,
  failed: colors.danger,
};

const statusLabels: Record<AccountNotification["status"], string> = {
  pending: "Queued",
  retrying: "Retrying",
  sent: "Sent",
  skipped: "Skipped",
  failed: "Failed",
};

function shopName(item: AccountNotification): string {
  const name = item.shop.name;
  const slug = item.shop.slug;
  return typeof name === "string" ? name : typeof slug === "string" ? slug : "Shop";
}

function channelLabel(channel: string): string {
  if (channel === "in_app") return "In-app";
  if (channel === "email") return "Email";
  if (channel === "push") return "Push";
  return channel;
}

function deviceLabel(token: PushToken): string {
  if (token.platform === "ios") return "iOS device";
  if (token.platform === "android") return "Android device";
  return token.platform;
}

export default function NotificationsScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { token } = useAuth();
  const notifications = useMyNotifications(token);
  const pushTokens = useMyPushTokens(token);
  const items = notifications.data?.pages.flatMap((page) => page.items) ?? [];
  const devices = pushTokens.data?.items ?? [];
  const activeDevices = devices.filter((device) => !device.revoked_at).length;
  const revokedDevices = devices.length - activeDevices;
  const pushUnavailable = pushTokens.isError && devices.length === 0;
  const refreshing = notifications.isRefetching || pushTokens.isRefetching;

  function refresh() {
    void notifications.refetch();
    void pushTokens.refetch();
  }

  if (!token) {
    return (
      <View style={styles.screen}>
        <EmptyState
          actionLabel="Sign in"
          body="Sign in with your email to see delivery status for holds, requests, and restock alerts."
          icon="log-in-outline"
          onAction={() => router.replace("/account")}
          title="Sign in to view notifications"
        />
      </View>
    );
  }

  if (notifications.isLoading || pushTokens.isLoading) {
    return <LoadingState label="Loading notification delivery…" />;
  }

  if (notifications.error) {
    return (
      <ErrorState
        message={
          notifications.error instanceof Error
            ? notifications.error.message
            : "Could not load your notification delivery log."
        }
        onRetry={() => void notifications.refetch()}
      />
    );
  }

  return (
    <View style={styles.screen}>
      <ScrollView
        contentContainerStyle={{
          padding: spacing.lg,
          paddingBottom: insets.bottom + spacing.xxl,
          gap: spacing.lg,
        }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={refresh} />}
        showsVerticalScrollIndicator={false}
      >
        <View style={styles.intro}>
          <Text style={styles.eyebrow}>NOTIFICATION DELIVERY</Text>
          <Text style={styles.title}>Know what reached you.</Text>
          <Text style={styles.subtitle}>
            Every push and in-app update is listed with its delivery status. Failed and skipped
            items stay visible so you can check your settings or this device.
          </Text>
        </View>

        <View style={styles.devicesCard}>
          <View style={styles.sectionHeader}>
            <View style={styles.sectionTitleWrap}>
              <Ionicons name="phone-portrait-outline" size={18} color={colors.primary} />
              <Text style={styles.sectionTitle}>Push devices</Text>
            </View>
            <Text style={styles.sectionMeta}>
              {pushUnavailable
                ? "Unavailable"
                : `${activeDevices} active${revokedDevices > 0 ? ` · ${revokedDevices} revoked` : ""}`}
            </Text>
          </View>

          {pushUnavailable ? (
            <Text style={styles.itemError}>Could not load push-device status.</Text>
          ) : devices.length === 0 ? (
            <Text style={styles.body}>
              This account has no registered push devices. Enable push on the Account screen to
              receive hold and request updates on this device.
            </Text>
          ) : (
            <View style={styles.deviceList}>
              {devices.map((device) => {
                const revoked = Boolean(device.revoked_at);
                return (
                  <View key={device.id} style={styles.deviceRow}>
                    <View style={styles.deviceMain}>
                      <Text style={styles.deviceName}>{deviceLabel(device)}</Text>
                      <Text style={styles.deviceMeta}>
                        {revoked ? "Token revoked" : "Active"} · registered{" "}
                        {formatDateTime(device.created_at)}
                      </Text>
                      {device.failure_count > 0 ? (
                        <Text style={styles.deviceError}>
                          {device.failure_count} failed attempt
                          {device.failure_count === 1 ? "" : "s"}
                          {device.last_failure_at
                            ? ` · last ${formatDateTime(device.last_failure_at)}`
                            : ""}
                        </Text>
                      ) : null}
                    </View>
                    <View
                      style={[
                        styles.deviceStatus,
                        revoked ? styles.deviceStatusOff : styles.deviceStatusOn,
                      ]}
                    >
                      <Text
                        style={[
                          styles.deviceStatusText,
                          revoked ? styles.deviceStatusTextOff : styles.deviceStatusTextOn,
                        ]}
                      >
                        {revoked ? "Revoked" : "Active"}
                      </Text>
                    </View>
                  </View>
                );
              })}
            </View>
          )}

          <PrimaryButton
            label={activeDevices > 0 ? "Manage push settings" : "Enable push notifications"}
            onPress={() => router.push("/account")}
            variant="secondary"
          />
        </View>

        <View style={styles.sectionHeader}>
          <View style={styles.sectionTitleWrap}>
            <Ionicons name="list-outline" size={18} color={colors.primary} />
            <Text style={styles.sectionTitle}>Recent delivery attempts</Text>
          </View>
          <Text style={styles.sectionMeta}>{items.length} shown</Text>
        </View>

        {items.length === 0 ? (
          <EmptyState
            body="When a hold is ready, a special order is quoted, or a restock alert is sent, its delivery status will appear here."
            icon="notifications-outline"
            title="No notification activity yet"
          />
        ) : (
          <View style={styles.list}>
            {items.map((item) => (
              <View key={`${item.id}`} style={styles.itemCard}>
                <View style={styles.itemTop}>
                  <View style={styles.itemChannel}>
                    <View
                      style={[styles.statusDot, { backgroundColor: statusColors[item.status] }]}
                    />
                    <Text style={styles.channel}>{channelLabel(item.channel)}</Text>
                  </View>
                  <Text style={[styles.status, { color: statusColors[item.status] }]}>
                    {statusLabels[item.status]}
                  </Text>
                </View>
                <Text numberOfLines={2} style={styles.itemTitle}>
                  {item.title}
                </Text>
                <Text style={styles.itemShop}>{shopName(item)}</Text>
                <Text style={styles.itemMeta}>
                  {formatDateTime(item.created_at)}
                  {item.attempts > 0
                    ? ` · ${item.attempts} attempt${item.attempts === 1 ? "" : "s"}`
                    : ""}
                </Text>
                {item.error && item.status !== "sent" ? (
                  <Text style={styles.itemError}>{item.error}</Text>
                ) : null}
              </View>
            ))}
          </View>
        )}

        {notifications.hasNextPage ? (
          <PrimaryButton
            label="Load older notifications"
            loading={notifications.isFetchingNextPage}
            onPress={() => void notifications.fetchNextPage()}
            variant="secondary"
          />
        ) : null}

        <Text style={styles.note}>
          Delivery status is recorded by the platform worker. In-app entries are recorded here and
          are not sent through email or push. Skipped entries mean your account or this device was
          opted out at the time. Invalid device tokens are revoked automatically when the push
          provider rejects them.
        </Text>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.background },
  intro: {
    backgroundColor: colors.primary,
    borderRadius: radii.lg,
    padding: spacing.lg,
    gap: spacing.sm,
  },
  eyebrow: {
    color: "#D8E8E1",
    fontSize: 10,
    fontWeight: "900",
    letterSpacing: 1.4,
  },
  title: { color: colors.white, fontSize: type.title, fontWeight: "900", letterSpacing: -0.4 },
  subtitle: { color: "#D8E8E1", fontSize: type.small, lineHeight: 19 },
  body: { color: colors.inkMuted, fontSize: type.small, lineHeight: 19 },
  note: { color: colors.inkMuted, fontSize: type.tiny, lineHeight: 17 },
  devicesCard: {
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.line,
    borderRadius: radii.lg,
    padding: spacing.lg,
    gap: spacing.md,
  },
  sectionHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: spacing.sm,
  },
  sectionTitleWrap: { flexDirection: "row", alignItems: "center", gap: spacing.sm, flex: 1 },
  sectionTitle: { color: colors.ink, fontSize: type.heading, fontWeight: "800" },
  sectionMeta: { color: colors.inkMuted, fontSize: type.tiny, fontWeight: "700" },
  deviceList: { gap: spacing.sm },
  deviceRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    borderTopWidth: 1,
    borderTopColor: colors.line,
    paddingTop: spacing.sm,
  },
  deviceMain: { flex: 1, gap: 2 },
  deviceName: { color: colors.ink, fontSize: type.small, fontWeight: "800" },
  deviceMeta: { color: colors.inkMuted, fontSize: type.tiny },
  deviceError: { color: colors.danger, fontSize: type.tiny, lineHeight: 16 },
  deviceStatus: { borderRadius: radii.pill, paddingHorizontal: spacing.sm, paddingVertical: 3 },
  deviceStatusOn: { backgroundColor: colors.successSoft },
  deviceStatusOff: { backgroundColor: colors.dangerSoft },
  deviceStatusText: { fontSize: 10, fontWeight: "900", letterSpacing: 0.4 },
  deviceStatusTextOn: { color: colors.success },
  deviceStatusTextOff: { color: colors.danger },
  list: { gap: spacing.md },
  itemCard: {
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.line,
    borderRadius: radii.lg,
    padding: spacing.lg,
    gap: spacing.xs,
  },
  itemTop: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  itemChannel: { flexDirection: "row", alignItems: "center", gap: spacing.xs },
  statusDot: { width: 8, height: 8, borderRadius: 4 },
  channel: { color: colors.inkMuted, fontSize: type.tiny, fontWeight: "800" },
  status: { fontSize: type.tiny, fontWeight: "900" },
  itemTitle: { color: colors.ink, fontSize: type.body, fontWeight: "800", lineHeight: 20 },
  itemShop: { color: colors.inkMuted, fontSize: type.small },
  itemMeta: { color: colors.inkMuted, fontSize: type.tiny },
  itemError: { color: colors.danger, fontSize: type.tiny, lineHeight: 16 },
});
