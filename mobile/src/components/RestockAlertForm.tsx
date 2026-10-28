import { Ionicons } from "@expo/vector-icons";
import { useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import { createRestockAlert, unsubscribeRestockAlert } from "../api/client";
import type { RestockAlertCreate, StockItem } from "../api/types";
import { Field } from "./Field";
import { PrimaryButton } from "./PrimaryButton";
import { useRestockAlerts } from "../state/restockAlerts";
import { colors, radii, spacing, type } from "../theme";

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

type Props = {
  shopSlug: string;
  shopName: string;
  item: StockItem;
};

export function RestockAlertForm({ shopSlug, shopName, item }: Props) {
  const { findForVariant, getToken, hydrated, remove, save } = useRestockAlerts();
  const saved = findForVariant(
    shopSlug,
    item.card.id,
    item.finish,
    item.condition,
    item.language,
  );

  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [emailError, setEmailError] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [unsubscribing, setUnsubscribing] = useState(false);

  async function subscribe() {
    if (!hydrated) return;
    const value = email.trim();
    if (!EMAIL.test(value)) {
      setEmailError("Enter a valid email address.");
      return;
    }
    setEmailError(null);
    setSubmitError(null);
    setSubmitting(true);
    try {
      const payload: RestockAlertCreate = {
        email: value,
        name: name.trim() || null,
        card_id: item.card.id,
        finish: item.finish as RestockAlertCreate["finish"],
        condition: item.condition as RestockAlertCreate["condition"],
        language: item.language,
      };
      const alert = await createRestockAlert(shopSlug, payload);
      await save(alert, {
        shopSlug,
        shopName,
        cardName: item.card.name,
        stockId: item.stock_id,
      });
      setEmail("");
      setName("");
    } catch (error) {
      setSubmitError(error instanceof Error ? error.message : "Could not save this alert.");
    } finally {
      setSubmitting(false);
    }
  }

  async function unsubscribe() {
    if (!saved) return;
    setSubmitError(null);
    setUnsubscribing(true);
    try {
      const token = await getToken(saved.id);
      if (!token) {
        throw new Error("This alert is missing its guest token. Add it again from this device.");
      }
      await unsubscribeRestockAlert(shopSlug, saved.id, token);
      await remove(saved.id);
    } catch (error) {
      setSubmitError(error instanceof Error ? error.message : "Could not remove this alert.");
    } finally {
      setUnsubscribing(false);
    }
  }

  if (!hydrated) {
    return (
      <View style={styles.panel}>
        <Text style={styles.body}>Loading your alerts…</Text>
      </View>
    );
  }

  return (
    <View style={styles.panel}>
      <View style={styles.headingRow}>
        <View style={styles.icon}>
          <Ionicons name="notifications-outline" size={19} color={colors.primary} />
        </View>
        <View style={styles.headingText}>
          <Text style={styles.title}>{saved ? "You’re on the list" : "Notify me"}</Text>
          <Text style={styles.body}>
            {saved
              ? `We’ll email ${saved.email} when this exact variant is back at ${shopName}.`
              : `Get one email from ${shopName} when this variant is back in stock.`}
          </Text>
        </View>
      </View>

      {saved ? (
        <View style={styles.savedBox}>
          <Ionicons name="checkmark-circle-outline" size={18} color={colors.success} />
          <Text style={styles.savedText}>Your alert is saved on this device.</Text>
        </View>
      ) : (
        <View style={styles.form}>
          <Field
            autoCapitalize="none"
            autoComplete="email"
            error={emailError}
            keyboardType="email-address"
            label="Email"
            onChangeText={setEmail}
            placeholder="you@example.com"
            textContentType="emailAddress"
            value={email}
          />
          <Field
            autoCapitalize="words"
            autoComplete="name"
            label="Name (optional)"
            onChangeText={setName}
            placeholder="Your name"
            textContentType="name"
            value={name}
          />
        </View>
      )}

      {submitError ? (
        <View style={styles.errorBox}>
          <Ionicons name="alert-circle-outline" size={18} color={colors.danger} />
          <Text style={styles.errorText}>{submitError}</Text>
        </View>
      ) : null}

      {saved ? (
        <PrimaryButton
          label="Remove this alert"
          loading={unsubscribing}
          onPress={() => void unsubscribe()}
          variant="secondary"
        />
      ) : (
        <PrimaryButton
          label="Email me when it’s back"
          loading={submitting}
          onPress={() => void subscribe()}
        />
      )}

      <Text style={styles.note}>
        This is a single back-in-stock email, not a newsletter. You can remove it at any time.
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  panel: {
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.line,
    borderRadius: radii.lg,
    padding: spacing.lg,
    gap: spacing.md,
  },
  headingRow: { flexDirection: "row", gap: spacing.md, alignItems: "center" },
  icon: {
    width: 38,
    height: 38,
    borderRadius: 13,
    backgroundColor: colors.primarySoft,
    alignItems: "center",
    justifyContent: "center",
  },
  headingText: { flex: 1, gap: 2 },
  title: { color: colors.ink, fontSize: type.heading, fontWeight: "900" },
  body: { color: colors.inkMuted, fontSize: type.small, lineHeight: 19 },
  form: { gap: spacing.md },
  savedBox: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    backgroundColor: colors.successSoft,
    borderRadius: radii.md,
    padding: spacing.md,
  },
  savedText: { flex: 1, color: colors.success, fontSize: type.small, fontWeight: "700" },
  errorBox: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: spacing.sm,
    backgroundColor: colors.dangerSoft,
    borderRadius: radii.md,
    padding: spacing.md,
  },
  errorText: { flex: 1, color: colors.danger, fontSize: type.small, lineHeight: 19 },
  note: {
    color: colors.inkMuted,
    fontSize: type.tiny,
    lineHeight: 17,
    textAlign: "center",
  },
});
