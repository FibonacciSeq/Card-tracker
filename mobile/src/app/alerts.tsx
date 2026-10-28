import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { useState } from "react";
import { Modal, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { unsubscribeRestockAlert } from "../api/client";
import { EmptyState } from "../components/EmptyState";
import { LoadingState } from "../components/LoadingState";
import { PrimaryButton } from "../components/PrimaryButton";
import { formatDateTime, titleCase } from "../lib/format";
import { useRestockAlerts, type SavedRestockAlert } from "../state/restockAlerts";
import { colors, radii, spacing, type } from "../theme";

export default function AlertsScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { alerts, getToken, hydrated, remove } = useRestockAlerts();
  const [confirming, setConfirming] = useState<SavedRestockAlert | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function unsubscribe(alert: SavedRestockAlert) {
    setError(null);
    setBusyId(alert.id);
    try {
      const token = await getToken(alert.id);
      if (!token) {
        throw new Error("This alert is missing its guest token. Add it again from a card page.");
      }
      await unsubscribeRestockAlert(alert.shopSlug, alert.id, token);
      await remove(alert.id);
      setConfirming(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not remove this alert.");
    } finally {
      setBusyId(null);
    }
  }

  if (!hydrated) return <LoadingState label="Loading alerts…" />;

  return (
    <View style={styles.screen}>
      <ScrollView
        contentContainerStyle={{
          padding: spacing.lg,
          paddingBottom: insets.bottom + spacing.xxl,
          gap: spacing.lg,
        }}
        showsVerticalScrollIndicator={false}
      >
        <View style={styles.intro}>
          <Text style={styles.eyebrow}>RESTOCK ALERTS</Text>
          <Text style={styles.title}>We’ll tell you when it’s back.</Text>
          <Text style={styles.subtitle}>
            These are one-off emails for the exact card variant you asked about. No newsletter.
          </Text>
        </View>

        {error ? (
          <View style={styles.errorBox}>
            <Ionicons name="alert-circle-outline" size={18} color={colors.danger} />
            <Text style={styles.errorText}>{error}</Text>
          </View>
        ) : null}

        {alerts.length === 0 ? (
          <EmptyState
            icon="notifications-outline"
            title="No restock alerts"
            body="Open a sold-out card at a shop and ask to be emailed when it returns."
            actionLabel="Browse shops"
            onAction={() => router.replace("/")}
          />
        ) : (
          <View style={styles.list}>
            {alerts.map((alert) => (
              <View key={alert.id} style={styles.card}>
                <Pressable
                  accessibilityHint="Opens the card in the shop"
                  accessibilityRole="button"
                  onPress={() =>
                    router.push(`/shop/${alert.shopSlug}/card/${alert.stockId}`)
                  }
                  style={({ pressed }) => [styles.cardMain, pressed && styles.pressed]}
                >
                  <View style={styles.cardTop}>
                    <View style={styles.cardTitleWrap}>
                      <Text style={styles.shop}>{alert.shopName}</Text>
                      <Text numberOfLines={2} style={styles.cardName}>
                        {alert.cardName}
                      </Text>
                    </View>
                    <Ionicons name="chevron-forward" size={18} color={colors.inkMuted} />
                  </View>
                  <Text style={styles.variant}>
                    {titleCase(alert.finish)} · {alert.condition} ·{" "}
                    {alert.language.toUpperCase()}
                  </Text>
                  <Text style={styles.email}>{alert.email}</Text>
                  <Text style={styles.created}>Added {formatDateTime(alert.created_at)}</Text>
                </Pressable>

                <Pressable
                  accessibilityLabel={`Remove restock alert for ${alert.cardName}`}
                  accessibilityRole="button"
                  onPress={() => {
                    setError(null);
                    setConfirming(alert);
                  }}
                  style={({ pressed }) => [styles.removeButton, pressed && styles.pressed]}
                >
                  <Ionicons name="trash-outline" size={16} color={colors.danger} />
                  <Text style={styles.removeLabel}>Remove alert</Text>
                </Pressable>
              </View>
            ))}
          </View>
        )}
      </ScrollView>

      <Modal
        animationType="fade"
        onRequestClose={() => setConfirming(null)}
        transparent
        visible={confirming !== null}
      >
        <View style={styles.modalOverlay}>
          <View style={styles.modalCard}>
            <View style={styles.modalIcon}>
              <Ionicons name="notifications-off-outline" size={24} color={colors.danger} />
            </View>
            <Text style={styles.modalTitle}>Remove this alert?</Text>
            <Text style={styles.modalBody}>
              {confirming
                ? `You will not be emailed when ${confirming.cardName} is back at ${confirming.shopName}.`
                : ""}
            </Text>
            {error ? <Text style={styles.modalError}>{error}</Text> : null}
            <PrimaryButton
              label="Keep alert"
              onPress={() => setConfirming(null)}
              variant="secondary"
            />
            <PrimaryButton
              label="Remove alert"
              loading={busyId === confirming?.id}
              onPress={() => {
                if (confirming) void unsubscribe(confirming);
              }}
              variant="danger"
            />
          </View>
        </View>
      </Modal>
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
  list: { gap: spacing.md },
  card: {
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.line,
    borderRadius: radii.lg,
    overflow: "hidden",
  },
  cardMain: { padding: spacing.lg, gap: spacing.xs },
  cardTop: {
    flexDirection: "row",
    alignItems: "flex-start",
    justifyContent: "space-between",
    gap: spacing.sm,
  },
  cardTitleWrap: { flex: 1, gap: 2 },
  shop: { color: colors.inkMuted, fontSize: type.tiny, fontWeight: "700" },
  cardName: { color: colors.ink, fontSize: type.body, fontWeight: "800", lineHeight: 20 },
  variant: { color: colors.inkMuted, fontSize: type.small },
  email: { color: colors.ink, fontSize: type.small, fontWeight: "700", marginTop: spacing.xs },
  created: { color: colors.inkMuted, fontSize: type.tiny },
  removeButton: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.xs,
    minHeight: 44,
    borderTopWidth: 1,
    borderTopColor: colors.line,
    backgroundColor: colors.dangerSoft,
  },
  removeLabel: { color: colors.danger, fontSize: type.small, fontWeight: "800" },
  pressed: { opacity: 0.82 },
  errorBox: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: spacing.sm,
    backgroundColor: colors.dangerSoft,
    borderRadius: radii.md,
    padding: spacing.md,
  },
  errorText: { flex: 1, color: colors.danger, fontSize: type.small, lineHeight: 19 },
  modalOverlay: {
    flex: 1,
    backgroundColor: colors.overlay,
    alignItems: "center",
    justifyContent: "center",
    padding: spacing.xl,
  },
  modalCard: {
    width: "100%",
    maxWidth: 420,
    backgroundColor: colors.surface,
    borderRadius: radii.lg,
    padding: spacing.xl,
    gap: spacing.md,
  },
  modalIcon: {
    width: 46,
    height: 46,
    borderRadius: 16,
    backgroundColor: colors.dangerSoft,
    alignItems: "center",
    justifyContent: "center",
  },
  modalTitle: { color: colors.ink, fontSize: type.title, fontWeight: "900" },
  modalBody: {
    color: colors.inkMuted,
    fontSize: type.body,
    lineHeight: 22,
    marginBottom: spacing.sm,
  },
  modalError: { color: colors.danger, fontSize: type.small, lineHeight: 19 },
});
