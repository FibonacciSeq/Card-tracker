import { Ionicons } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useRef, useState } from "react";
import {
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { createReservation } from "../../../api/client";
import { useShop } from "../../../api/queries";
import type { ReservationCreate } from "../../../api/types";
import { EmptyState } from "../../../components/EmptyState";
import { Field } from "../../../components/Field";
import { PrimaryButton } from "../../../components/PrimaryButton";
import { formatMoney, titleCase } from "../../../lib/format";
import { newIdempotencyKey } from "../../../lib/idempotency";
import { useCart } from "../../../state/cart";
import { useReservations } from "../../../state/reservations";
import { colors, radii, spacing, type } from "../../../theme";

type Errors = {
  name?: string;
  email?: string;
};

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export default function CartScreen() {
  const { slug } = useLocalSearchParams<{ slug: string }>();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const shopQuery = useShop(slug);
  const cart = useCart();
  const { save } = useReservations();
  const lines = cart.linesFor(slug);
  const total = cart.totalFor(slug);

  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [note, setNote] = useState("");
  const [errors, setErrors] = useState<Errors>({});
  const [submitting, setSubmitting] = useState(false);
  const [apiError, setApiError] = useState<string | null>(null);
  const idempotencyKey = useRef(newIdempotencyKey());

  const shop = shopQuery.data;

  async function submit() {
    const nextErrors: Errors = {};
    if (!name.trim()) nextErrors.name = "Enter the name for the hold.";
    if (!EMAIL.test(email.trim())) nextErrors.email = "Enter a valid email address.";
    setErrors(nextErrors);
    setApiError(null);
    if (Object.keys(nextErrors).length > 0) return;

    const payload: ReservationCreate = {
      customer: {
        name: name.trim(),
        email: email.trim(),
        phone: phone.trim(),
      },
      note: note.trim(),
      items: lines.map((line) => ({
        stock_id: line.stockId,
        quantity: line.quantity,
      })),
    };

    setSubmitting(true);
    try {
      const reservation = await createReservation(slug, payload, idempotencyKey.current);
      await save(reservation, reservation.access_token ?? "");
      cart.clear(slug);
      idempotencyKey.current = newIdempotencyKey();
      router.replace(`/reservation/${reservation.id}`);
    } catch (error) {
      setApiError(error instanceof Error ? error.message : "Could not create the hold.");
    } finally {
      setSubmitting(false);
    }
  }

  if (lines.length === 0) {
    return (
      <View style={styles.screen}>
        <EmptyState
          icon="bag-handle-outline"
          title="Your hold is empty"
          body="Add a few cards from the shop shelf and come back here."
          actionLabel="Back to the shop"
          onAction={() => router.back()}
        />
      </View>
    );
  }

  return (
    <KeyboardAvoidingView
      behavior={Platform.OS === "ios" ? "padding" : undefined}
      style={styles.screen}
    >
      <ScrollView
        contentContainerStyle={{
          padding: spacing.lg,
          paddingBottom: insets.bottom + spacing.xxl,
          gap: spacing.xl,
        }}
        keyboardShouldPersistTaps="handled"
        showsVerticalScrollIndicator={false}
      >
        <View style={styles.summary}>
          <Text style={styles.eyebrow}>YOUR HOLD</Text>
          <Text style={styles.summaryTitle}>
            {lines.length} {lines.length === 1 ? "card" : "cards"} from{" "}
            {shop?.brand_name || shop?.name || "this shop"}
          </Text>
          <View style={styles.lines}>
            {lines.map((line) => (
              <View key={line.stockId} style={styles.line}>
                <View style={styles.lineBody}>
                  <Text numberOfLines={2} style={styles.lineName}>
                    {line.item.card.name}
                  </Text>
                  <Text style={styles.lineMeta}>
                    {line.item.card.set_code.toUpperCase()} · #{line.item.card.collector_number} ·{" "}
                    {titleCase(line.item.finish)} · {line.item.condition}
                  </Text>
                  <Text style={styles.linePrice}>
                    {formatMoney(line.item.price)} each
                  </Text>
                </View>
                <View style={styles.quantity}>
                  <Pressable
                    accessibilityLabel={`Remove one ${line.item.card.name}`}
                    accessibilityRole="button"
                    hitSlop={8}
                    onPress={() => cart.setQuantity(slug, line.stockId, line.quantity - 1)}
                    style={styles.step}
                  >
                    <Ionicons name="remove" size={16} color={colors.primary} />
                  </Pressable>
                  <Text style={styles.quantityText}>{line.quantity}</Text>
                  <Pressable
                    accessibilityLabel={`Add one ${line.item.card.name}`}
                    accessibilityRole="button"
                    disabled={line.quantity >= line.item.available}
                    hitSlop={8}
                    onPress={() => cart.setQuantity(slug, line.stockId, line.quantity + 1)}
                    style={[styles.step, line.quantity >= line.item.available && styles.stepOff]}
                  >
                    <Ionicons name="add" size={16} color={colors.primary} />
                  </Pressable>
                </View>
              </View>
            ))}
          </View>
          <View style={styles.totalRow}>
            <Text style={styles.totalLabel}>Total</Text>
            <Text style={styles.totalValue}>{formatMoney(total)}</Text>
          </View>
        </View>

        <View style={styles.form}>
          <View style={styles.formTitleRow}>
            <View style={styles.formIcon}>
              <Ionicons name="person-outline" size={18} color={colors.primary} />
            </View>
            <View style={styles.formTitleText}>
              <Text style={styles.formTitle}>Contact details</Text>
              <Text style={styles.formSubtitle}>
                The shop uses these to prepare and hold your cards.
              </Text>
            </View>
          </View>
          <Field
            autoCapitalize="words"
            autoComplete="name"
            error={errors.name}
            label="Name"
            onChangeText={setName}
            placeholder="Your name"
            returnKeyType="next"
            textContentType="name"
            value={name}
          />
          <Field
            autoCapitalize="none"
            autoComplete="email"
            error={errors.email}
            keyboardType="email-address"
            label="Email"
            onChangeText={setEmail}
            placeholder="you@example.com"
            returnKeyType="next"
            textContentType="emailAddress"
            value={email}
          />
          <Field
            autoCapitalize="none"
            autoComplete="tel"
            keyboardType="phone-pad"
            label="Phone (optional)"
            onChangeText={setPhone}
            placeholder="For pickup questions"
            returnKeyType="next"
            textContentType="telephoneNumber"
            value={phone}
          />
          <Field
            label="Note (optional)"
            maxLength={2000}
            multiline
            numberOfLines={3}
            onChangeText={setNote}
            placeholder="Anything the shop should know?"
            value={note}
          />
        </View>

        <View style={styles.policy}>
          <Ionicons name="time-outline" size={18} color={colors.primary} />
          <Text style={styles.policyText}>
            The shop holds your cards for {shop?.hold_hours ?? 24} hours. You can cancel from this
            app before pickup. Payment is arranged directly with the shop.
          </Text>
        </View>

        {apiError ? (
          <View style={styles.errorBox}>
            <Ionicons name="alert-circle-outline" size={18} color={colors.danger} />
            <Text style={styles.errorText}>{apiError}</Text>
          </View>
        ) : null}

        <PrimaryButton
          label="Request this hold"
          loading={submitting}
          onPress={() => void submit()}
        />
        <Text style={styles.disclaimer}>
          You will receive a reservation reference. No payment is taken in the app.
        </Text>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.background },
  summary: {
    backgroundColor: colors.surface,
    borderRadius: radii.lg,
    borderWidth: 1,
    borderColor: colors.line,
    padding: spacing.lg,
    gap: spacing.md,
  },
  eyebrow: {
    color: colors.accent,
    fontSize: 10,
    fontWeight: "900",
    letterSpacing: 1.2,
  },
  summaryTitle: {
    color: colors.ink,
    fontSize: type.heading,
    fontWeight: "900",
    lineHeight: 24,
  },
  lines: { gap: spacing.md },
  line: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    borderTopWidth: 1,
    borderTopColor: colors.line,
    paddingTop: spacing.md,
  },
  lineBody: { flex: 1, gap: 2 },
  lineName: { color: colors.ink, fontSize: type.body, fontWeight: "800" },
  lineMeta: { color: colors.inkMuted, fontSize: type.tiny },
  linePrice: { color: colors.inkMuted, fontSize: type.small, marginTop: 2 },
  quantity: {
    flexDirection: "row",
    alignItems: "center",
    borderWidth: 1,
    borderColor: colors.line,
    borderRadius: radii.pill,
    backgroundColor: colors.background,
    overflow: "hidden",
  },
  step: { width: 32, height: 30, alignItems: "center", justifyContent: "center" },
  stepOff: { opacity: 0.35 },
  quantityText: {
    minWidth: 22,
    textAlign: "center",
    color: colors.ink,
    fontSize: type.small,
    fontWeight: "800",
  },
  totalRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    borderTopWidth: 1,
    borderTopColor: colors.line,
    paddingTop: spacing.md,
  },
  totalLabel: { color: colors.inkMuted, fontSize: type.body, fontWeight: "700" },
  totalValue: { color: colors.ink, fontSize: type.title, fontWeight: "900" },
  form: {
    backgroundColor: colors.surface,
    borderRadius: radii.lg,
    borderWidth: 1,
    borderColor: colors.line,
    padding: spacing.lg,
    gap: spacing.md,
  },
  formTitleRow: { flexDirection: "row", gap: spacing.md, alignItems: "center" },
  formIcon: {
    width: 38,
    height: 38,
    borderRadius: 13,
    backgroundColor: colors.primarySoft,
    alignItems: "center",
    justifyContent: "center",
  },
  formTitleText: { flex: 1, gap: 2 },
  formTitle: { color: colors.ink, fontSize: type.heading, fontWeight: "900" },
  formSubtitle: { color: colors.inkMuted, fontSize: type.small, lineHeight: 18 },
  policy: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: spacing.sm,
    backgroundColor: colors.primarySoft,
    borderRadius: radii.md,
    padding: spacing.md,
  },
  policyText: { flex: 1, color: colors.primary, fontSize: type.small, lineHeight: 19 },
  errorBox: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: spacing.sm,
    backgroundColor: colors.dangerSoft,
    borderRadius: radii.md,
    padding: spacing.md,
  },
  errorText: { flex: 1, color: colors.danger, fontSize: type.small, lineHeight: 19 },
  disclaimer: {
    color: colors.inkMuted,
    fontSize: type.tiny,
    lineHeight: 17,
    textAlign: "center",
  },
});
