import { Ionicons } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useState } from "react";
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
import { useQueryClient } from "@tanstack/react-query";

import { createCardRequest } from "../../api/client";
import { accountKeys } from "../../api/queries";
import type { CardRequestCreate, Condition, Finish } from "../../api/types";
import { EmptyState } from "../../components/EmptyState";
import { Field } from "../../components/Field";
import { PrimaryButton } from "../../components/PrimaryButton";
import { useAuth } from "../../state/auth";
import { useSpecialOrders } from "../../state/specialOrders";
import { colors, radii, spacing, type } from "../../theme";

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const FINISHES: { value: Finish; label: string }[] = [
  { value: "nonfoil", label: "Nonfoil" },
  { value: "foil", label: "Foil" },
  { value: "etched", label: "Etched" },
];
const CONDITIONS: { value: Condition; label: string }[] = [
  { value: "NM", label: "NM" },
  { value: "LP", label: "LP" },
  { value: "MP", label: "MP" },
  { value: "HP", label: "HP" },
  { value: "DMG", label: "DMG" },
];

type Errors = {
  customerName?: string;
  email?: string;
  cardName?: string;
  quantity?: string;
  targetPrice?: string;
};

export default function NewRequestScreen() {
  const params = useLocalSearchParams<{
    shopSlug?: string;
    shopName?: string;
    cardId?: string;
    name?: string;
    setCode?: string;
    collectorNumber?: string;
    finish?: string;
    condition?: string;
    language?: string;
  }>();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const queryClient = useQueryClient();
  const { customer, token } = useAuth();
  const { hydrated, save } = useSpecialOrders();

  const [customerName, setCustomerName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [cardName, setCardName] = useState(params.name ?? "");
  const [setCode, setSetCode] = useState(params.setCode ?? "");
  const [collectorNumber, setCollectorNumber] = useState(params.collectorNumber ?? "");
  const [finish, setFinish] = useState<Finish>(
    params.finish === "foil" || params.finish === "etched" ? params.finish : "nonfoil",
  );
  const [condition, setCondition] = useState<Condition>(
    CONDITIONS.some((item) => item.value === params.condition)
      ? (params.condition as Condition)
      : "NM",
  );
  const [language, setLanguage] = useState(params.language ?? "en");
  const [quantity, setQuantity] = useState("1");
  const [targetPrice, setTargetPrice] = useState("");
  const [note, setNote] = useState("");
  const [errors, setErrors] = useState<Errors>({});
  const [apiError, setApiError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const activeShopSlug = params.shopSlug ?? "";
  const shopName = params.shopName || "the shop";

  async function submit() {
    if (!hydrated) return;
    const contactEmail = token ? (customer?.email ?? "") : email.trim();
    const next: Errors = {};
    if (!customerName.trim()) next.customerName = "Enter your name.";
    if (!token && !EMAIL.test(contactEmail)) next.email = "Enter a valid email address.";
    if (!cardName.trim()) next.cardName = "Which card are you looking for?";
    const parsedQuantity = Number.parseInt(quantity, 10);
    if (!Number.isFinite(parsedQuantity) || parsedQuantity < 1 || parsedQuantity > 999) {
      next.quantity = "Choose a quantity between 1 and 999.";
    }
    let targetMinor: number | null = null;
    if (targetPrice.trim()) {
      const amount = Number(targetPrice.trim().replace(",", "."));
      if (!Number.isFinite(amount) || amount < 0) {
        next.targetPrice = "Enter a price like 12.50, or leave it empty.";
      } else {
        targetMinor = Math.round(amount * 100);
      }
    }
    setErrors(next);
    setApiError(null);
    if (Object.keys(next).length > 0) return;

    const payload: CardRequestCreate = {
      customer: {
        name: customerName.trim(),
        email: contactEmail,
        phone: phone.trim(),
      },
      card_id: params.cardId ?? null,
      requested_name: cardName.trim(),
      set_code: setCode.trim(),
      collector_number: collectorNumber.trim(),
      finish,
      condition,
      language: language.trim() || "en",
      quantity: parsedQuantity,
      target_price_minor: targetMinor,
      note: note.trim(),
    };

    setSubmitting(true);
    try {
      const request = await createCardRequest(activeShopSlug, payload, token);
      await save(request, { shopSlug: activeShopSlug, shopName });
      if (token) {
        await queryClient.invalidateQueries({ queryKey: accountKeys.cardRequests });
      }
      router.replace(`/requests/${request.id}`);
    } catch (error) {
      setApiError(error instanceof Error ? error.message : "Could not send this request.");
    } finally {
      setSubmitting(false);
    }
  }

  if (!activeShopSlug) {
    return (
      <View style={styles.screen}>
        <EmptyState
          icon="storefront-outline"
          title="Choose a shop first"
          body="Open a shop and choose Request a special order so the request goes directly to that shop."
          actionLabel="Browse shops"
          onAction={() => router.replace("/")}
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
          gap: spacing.lg,
        }}
        keyboardShouldPersistTaps="handled"
        showsVerticalScrollIndicator={false}
      >
        <View style={styles.intro}>
          <View style={styles.introIcon}>
            <Ionicons name="sparkles-outline" size={20} color={colors.accent} />
          </View>
          <View style={styles.introText}>
            <Text style={styles.introTitle}>Request a special order</Text>
            <Text style={styles.introBody}>
              Your request goes directly to {shopName}. It will reply with a quote if it can
              source the card. Nothing is reserved until you accept.
            </Text>
          </View>
        </View>

        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Shop</Text>
          <View style={styles.selectedShop}>
            <View style={styles.selectedShopIcon}>
              <Ionicons name="storefront-outline" size={20} color={colors.primary} />
            </View>
            <View style={styles.selectedShopText}>
              <Text style={styles.selectedShopName}>{shopName}</Text>
              <Text style={styles.selectedShopSlug}>@{activeShopSlug}</Text>
            </View>
          </View>
        </View>

        <View style={styles.section}>
          <Text style={styles.sectionTitle}>The card</Text>
          <Field
            autoCapitalize="words"
            error={errors.cardName}
            label="Card name"
            onChangeText={setCardName}
            placeholder="e.g. Lightning Bolt"
            value={cardName}
          />
          <View style={styles.row}>
            <View style={styles.half}>
              <Field
                autoCapitalize="characters"
                label="Set code"
                onChangeText={setSetCode}
                placeholder="LEB"
                value={setCode}
              />
            </View>
            <View style={styles.half}>
              <Field
                label="Collector number"
                onChangeText={setCollectorNumber}
                placeholder="161"
                value={collectorNumber}
              />
            </View>
          </View>
          <Choice label="Finish" onChange={setFinish} options={FINISHES} value={finish} />
          <Choice
            label="Condition"
            onChange={setCondition}
            options={CONDITIONS}
            value={condition}
          />
          <View style={styles.row}>
            <View style={styles.half}>
              <Field
                autoCapitalize="none"
                label="Language"
                maxLength={5}
                onChangeText={setLanguage}
                placeholder="en"
                value={language}
              />
            </View>
            <View style={styles.half}>
              <Field
                error={errors.quantity}
                keyboardType="number-pad"
                label="Quantity"
                onChangeText={setQuantity}
                value={quantity}
              />
            </View>
          </View>
          <Field
            error={errors.targetPrice}
            keyboardType="decimal-pad"
            label="Target price (optional)"
            onChangeText={setTargetPrice}
            placeholder="Leave empty for the shop’s quote"
            value={targetPrice}
          />
          <Field
            label="Note (optional)"
            maxLength={2000}
            multiline
            numberOfLines={3}
            onChangeText={setNote}
            placeholder="Edition, art, or anything else that matters"
            value={note}
          />
        </View>

        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Your contact details</Text>
          <Field
            autoCapitalize="words"
            autoComplete="name"
            error={errors.customerName}
            label="Name"
            onChangeText={setCustomerName}
            placeholder="Your name"
            textContentType="name"
            value={customerName}
          />
          <Field
            autoCapitalize="none"
            autoComplete="email"
            editable={!token}
            error={token ? null : errors.email}
            keyboardType="email-address"
            label="Email"
            onChangeText={setEmail}
            placeholder="you@example.com"
            textContentType="emailAddress"
            value={token ? (customer?.email ?? "") : email}
          />
          <Field
            autoCapitalize="none"
            autoComplete="tel"
            keyboardType="phone-pad"
            label="Phone (optional)"
            onChangeText={setPhone}
            placeholder="For quote questions"
            textContentType="telephoneNumber"
            value={phone}
          />
        </View>

        {apiError ? (
          <View style={styles.errorBox}>
            <Ionicons name="alert-circle-outline" size={18} color={colors.danger} />
            <Text style={styles.errorText}>{apiError}</Text>
          </View>
        ) : null}

        <PrimaryButton
          label={shopName === "the shop" ? "Send request" : `Send request to ${shopName}`}
          loading={submitting || !hydrated}
          onPress={() => void submit()}
        />
        <Text style={styles.disclaimer}>
          No payment is taken. The shop may decline if it cannot source the card.
        </Text>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

function Choice<T extends string>({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: { value: T; label: string }[];
  value: T;
  onChange: (value: T) => void;
}) {
  return (
    <View style={styles.choiceWrap}>
      <Text style={styles.choiceLabel}>{label}</Text>
      <View style={styles.choiceRow}>
        {options.map((option) => {
          const active = option.value === value;
          return (
            <Pressable
              key={option.value}
              accessibilityRole="button"
              accessibilityState={{ selected: active }}
              onPress={() => onChange(option.value)}
              style={[styles.choice, active && styles.choiceActive]}
            >
              <Text style={[styles.choiceText, active && styles.choiceTextActive]}>
                {option.label}
              </Text>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.background },
  intro: {
    flexDirection: "row",
    gap: spacing.md,
    alignItems: "center",
    backgroundColor: colors.accentSoft,
    borderRadius: radii.lg,
    padding: spacing.lg,
  },
  introIcon: {
    width: 42,
    height: 42,
    borderRadius: 14,
    backgroundColor: colors.surface,
    alignItems: "center",
    justifyContent: "center",
  },
  introText: { flex: 1, gap: 1 },
  introTitle: { color: colors.ink, fontSize: type.heading, fontWeight: "900" },
  introBody: { color: colors.inkMuted, fontSize: type.small, lineHeight: 19 },
  section: {
    backgroundColor: colors.surface,
    borderRadius: radii.lg,
    borderWidth: 1,
    borderColor: colors.line,
    padding: spacing.lg,
    gap: spacing.md,
  },
  sectionTitle: { color: colors.ink, fontSize: type.heading, fontWeight: "900" },
  selectedShop: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    backgroundColor: colors.background,
    borderRadius: radii.md,
    borderWidth: 1,
    borderColor: colors.line,
    padding: spacing.md,
  },
  selectedShopIcon: {
    width: 40,
    height: 40,
    borderRadius: 12,
    backgroundColor: colors.primarySoft,
    alignItems: "center",
    justifyContent: "center",
  },
  selectedShopText: { flex: 1, gap: 2 },
  selectedShopName: { color: colors.ink, fontSize: type.body, fontWeight: "800" },
  selectedShopSlug: { color: colors.primary, fontSize: type.small, fontWeight: "700" },
  row: { flexDirection: "row", gap: spacing.md },
  half: { flex: 1 },
  choiceWrap: { gap: 6 },
  choiceLabel: { color: colors.ink, fontSize: type.small, fontWeight: "700" },
  choiceRow: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  choice: {
    minHeight: 40,
    minWidth: 58,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: radii.pill,
    borderWidth: 1,
    borderColor: colors.line,
    backgroundColor: colors.background,
    paddingHorizontal: spacing.md,
  },
  choiceActive: { backgroundColor: colors.primarySoft, borderColor: colors.primary },
  choiceText: { color: colors.inkMuted, fontSize: type.small, fontWeight: "700" },
  choiceTextActive: { color: colors.primary },
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
