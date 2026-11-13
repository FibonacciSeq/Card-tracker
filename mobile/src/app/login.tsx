import { Ionicons } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useMemo, useState } from "react";
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

import { Field } from "../components/Field";
import { LoadingState } from "../components/LoadingState";
import { PrimaryButton } from "../components/PrimaryButton";
import { useAuth } from "../state/auth";
import { useLocale } from "../state/locale";
import { colors, radii, spacing, type } from "../theme";

type Mode = "signin" | "signup" | "reset";

export default function LoginScreen() {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { locale, setLocale, t } = useLocale();
  const {
    hydrated,
    isAuthenticated,
    login,
    requestSignupCode,
    requestPasswordReset,
    resetPassword,
    verifySignup,
  } = useAuth();
  const params = useLocalSearchParams<{ next?: string | string[] }>();
  const nextPath = useMemo(() => safeNextPath(params.next), [params.next]);

  const [mode, setMode] = useState<Mode>("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [code, setCode] = useState("");
  const [debugCode, setDebugCode] = useState<string | null>(null);
  const [resendIn, setResendIn] = useState(0);
  const [codeSent, setCodeSent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    if (hydrated && isAuthenticated) {
      router.replace(nextPath);
    }
  }, [hydrated, isAuthenticated, nextPath, router]);

  useEffect(() => {
    if (resendIn <= 0) return;
    const timer = setInterval(() => setResendIn((value) => Math.max(0, value - 1)), 1000);
    return () => clearInterval(timer);
  }, [resendIn]);

  function switchMode(next: Mode) {
    setMode(next);
    setPassword("");
    setNewPassword("");
    setConfirmPassword("");
    setCode("");
    setDebugCode(null);
    setResendIn(0);
    setCodeSent(false);
    setError(null);
    setNotice(null);
  }

  function describe(caught: unknown, fallback: string) {
    return caught instanceof Error ? caught.message : fallback;
  }

  async function submitSignIn() {
    setError(null);
    setNotice(null);
    setBusy(true);
    try {
      await login(email, password);
    } catch (caught) {
      setError(describe(caught, "Could not sign in."));
    } finally {
      setBusy(false);
    }
  }

  async function sendSignupCode() {
    setError(null);
    setNotice(null);
    setBusy(true);
    try {
      const result = await requestSignupCode(email);
      setCodeSent(true);
      setCode("");
      setDebugCode(result.debug_code ?? null);
      setResendIn(result.resend_after);
      setNotice(`${t("verificationSent")} ${email.trim().toLowerCase()}.`);
    } catch (caught) {
      setError(describe(caught, "Could not send a verification code."));
    } finally {
      setBusy(false);
    }
  }

  async function submitSignup() {
    if (newPassword.length < 8) {
      setError(t("passwordHint"));
      return;
    }
    if (newPassword !== confirmPassword) {
      setError(t("passwordsDoNotMatch"));
      return;
    }
    setError(null);
    setNotice(null);
    setBusy(true);
    try {
      await verifySignup(email, code, newPassword);
    } catch (caught) {
      setError(describe(caught, "Could not create your account."));
    } finally {
      setBusy(false);
    }
  }

  async function sendResetCode() {
    setError(null);
    setNotice(null);
    setBusy(true);
    try {
      const result = await requestPasswordReset(email);
      setCodeSent(true);
      setCode("");
      setDebugCode(result.debug_code ?? null);
      setResendIn(result.resend_after);
      setNotice(`${t("resetSent")} ${email.trim().toLowerCase()}.`);
    } catch (caught) {
      setError(describe(caught, "Could not send a reset code."));
    } finally {
      setBusy(false);
    }
  }

  async function submitReset() {
    if (newPassword.length < 8) {
      setError(t("passwordHint"));
      return;
    }
    if (newPassword !== confirmPassword) {
      setError(t("passwordsDoNotMatch"));
      return;
    }
    setError(null);
    setNotice(null);
    setBusy(true);
    try {
      await resetPassword(email, code, newPassword);
    } catch (caught) {
      setError(describe(caught, "Could not reset your password."));
    } finally {
      setBusy(false);
    }
  }

  if (!hydrated) return <LoadingState label="Checking your session…" />;
  if (isAuthenticated) return <LoadingState label="Opening Card Tracker…" />;

  const resendLabel =
    resendIn > 0 ? `${t("sendNewCodeIn")} ${resendIn}s` : t("sendNewCode");

  return (
    <KeyboardAvoidingView
      behavior={Platform.OS === "ios" ? "padding" : undefined}
      style={styles.screen}
    >
      <ScrollView
        contentContainerStyle={{
          padding: spacing.lg,
          paddingTop: insets.top + spacing.xl,
          paddingBottom: insets.bottom + spacing.xxl,
          gap: spacing.lg,
        }}
        keyboardShouldPersistTaps="handled"
        showsVerticalScrollIndicator={false}
      >
        <View style={styles.brandRow}>
          <View style={styles.brandMark}>
            <Ionicons name="diamond-outline" size={16} color={colors.primary} />
          </View>
          <Text style={styles.brandText}>CARD TRACKER</Text>
        </View>

        <View style={styles.hero}>
          <Text style={styles.eyebrow}>SECURE ACCESS</Text>
          <Text style={styles.title}>{t("loginTitle")}</Text>
          <Text style={styles.subtitle}>{t("loginSubtitle")}</Text>
        </View>

        <View style={styles.localeCard}>
          <View style={styles.localeHeader}>
            <Ionicons name="language-outline" size={18} color={colors.primary} />
            <Text style={styles.localeLabel}>{t("language")}</Text>
          </View>
          <View style={styles.localeRow}>
            <Pressable
              accessibilityRole="button"
              onPress={() => setLocale("en")}
              style={({ pressed }) => [
                styles.localeButton,
                locale === "en" && styles.localeButtonActive,
                pressed && styles.pressed,
              ]}
            >
              <Text
                style={[
                  styles.localeButtonText,
                  locale === "en" && styles.localeButtonTextActive,
                ]}
              >
                {t("english")}
              </Text>
            </Pressable>
            <Pressable
              accessibilityRole="button"
              onPress={() => setLocale("sr")}
              style={({ pressed }) => [
                styles.localeButton,
                locale === "sr" && styles.localeButtonActive,
                pressed && styles.pressed,
              ]}
            >
              <Text
                style={[
                  styles.localeButtonText,
                  locale === "sr" && styles.localeButtonTextActive,
                ]}
              >
                {t("serbian")}
              </Text>
            </Pressable>
          </View>
        </View>

        {mode === "reset" ? (
          <Pressable
            accessibilityRole="button"
            onPress={() => switchMode("signin")}
            style={({ pressed }) => [styles.backLink, pressed && styles.pressed]}
          >
            <Ionicons name="arrow-back" size={16} color={colors.primary} />
            <Text style={styles.backLinkText}>{t("backToSignIn")}</Text>
          </Pressable>
        ) : (
          <View style={styles.segment}>
            <Pressable
              accessibilityRole="button"
              accessibilityState={{ selected: mode === "signin" }}
              onPress={() => switchMode("signin")}
              style={({ pressed }) => [
                styles.segmentButton,
                mode === "signin" && styles.segmentButtonActive,
                pressed && styles.pressed,
              ]}
            >
              <Text
                style={[
                  styles.segmentLabel,
                  mode === "signin" && styles.segmentLabelActive,
                ]}
              >
                {t("signInTab")}
              </Text>
            </Pressable>
            <Pressable
              accessibilityRole="button"
              accessibilityState={{ selected: mode === "signup" }}
              onPress={() => switchMode("signup")}
              style={({ pressed }) => [
                styles.segmentButton,
                mode === "signup" && styles.segmentButtonActive,
                pressed && styles.pressed,
              ]}
            >
              <Text
                style={[
                  styles.segmentLabel,
                  mode === "signup" && styles.segmentLabelActive,
                ]}
              >
                {t("createAccountTab")}
              </Text>
            </Pressable>
          </View>
        )}

        {error ? <ErrorBox text={error} /> : null}
        {notice ? <Notice text={notice} /> : null}

        <View style={styles.card}>
          {mode === "signin" ? (
            <>
              <Field
                autoCapitalize="none"
                autoComplete="email"
                autoCorrect={false}
                keyboardType="email-address"
                label={t("emailLabel")}
                onChangeText={setEmail}
                placeholder="you@example.com"
                textContentType="emailAddress"
                value={email}
              />
              <Field
                autoCapitalize="none"
                autoComplete="current-password"
                autoCorrect={false}
                label={t("passwordLabel")}
                onChangeText={setPassword}
                placeholder="••••••••"
                secureTextEntry
                textContentType="password"
                value={password}
              />
              <PrimaryButton
                disabled={email.trim().length === 0 || password.length === 0}
                label={t("signInAction")}
                loading={busy}
                onPress={() => void submitSignIn()}
              />
              <Pressable
                accessibilityRole="button"
                onPress={() => switchMode("reset")}
                style={({ pressed }) => [styles.link, pressed && styles.pressed]}
              >
                <Text style={styles.linkText}>{t("forgotPassword")}</Text>
              </Pressable>
            </>
          ) : null}

          {mode === "signup" ? (
            <>
              <Field
                autoCapitalize="none"
                autoComplete="email"
                autoCorrect={false}
                editable={!busy && !codeSent}
                keyboardType="email-address"
                label={t("emailLabel")}
                onChangeText={setEmail}
                placeholder="you@example.com"
                textContentType="emailAddress"
                value={email}
              />
              {!codeSent ? (
                <PrimaryButton
                  disabled={email.trim().length === 0}
                  label={t("sendVerificationCode")}
                  loading={busy}
                  onPress={() => void sendSignupCode()}
                />
              ) : (
                <>
                  <Field
                    autoCapitalize="none"
                    autoComplete="one-time-code"
                    keyboardType="number-pad"
                    label={t("verificationCodeLabel")}
                    maxLength={6}
                    onChangeText={(value) => setCode(value.replace(/\D/g, "").slice(0, 6))}
                    placeholder="000000"
                    returnKeyType="done"
                    textContentType="oneTimeCode"
                    value={code}
                  />
                  <Field
                    autoCapitalize="none"
                    autoComplete="new-password"
                    autoCorrect={false}
                    label={t("newPasswordLabel")}
                    onChangeText={setNewPassword}
                    placeholder="••••••••"
                    secureTextEntry
                    textContentType="newPassword"
                    value={newPassword}
                  />
                  <Field
                    autoCapitalize="none"
                    autoComplete="new-password"
                    autoCorrect={false}
                    label={t("confirmPasswordLabel")}
                    onChangeText={setConfirmPassword}
                    placeholder="••••••••"
                    secureTextEntry
                    textContentType="newPassword"
                    value={confirmPassword}
                  />
                  <Text style={styles.hint}>{t("passwordHint")}</Text>
                  <PrimaryButton
                    disabled={
                      code.length !== 6 ||
                      newPassword.length < 8 ||
                      confirmPassword.length === 0
                    }
                    label={t("verifyAndCreate")}
                    loading={busy}
                    onPress={() => void submitSignup()}
                  />
                  <Pressable
                    accessibilityRole="button"
                    disabled={busy || resendIn > 0}
                    onPress={() => void sendSignupCode()}
                    style={({ pressed }) => [styles.link, pressed && styles.pressed]}
                  >
                    <Text
                      style={[
                        styles.linkText,
                        (busy || resendIn > 0) && styles.linkDisabled,
                      ]}
                    >
                      {resendLabel}
                    </Text>
                  </Pressable>
                  <DebugCode code={debugCode} />
                </>
              )}
            </>
          ) : null}

          {mode === "reset" ? (
            <>
              <Text style={styles.cardTitle}>{t("resetPasswordTitle")}</Text>
              <Text style={styles.cardBody}>{t("resetPasswordBody")}</Text>
              <Field
                autoCapitalize="none"
                autoComplete="email"
                autoCorrect={false}
                editable={!busy && !codeSent}
                keyboardType="email-address"
                label={t("emailLabel")}
                onChangeText={setEmail}
                placeholder="you@example.com"
                textContentType="emailAddress"
                value={email}
              />
              {!codeSent ? (
                <PrimaryButton
                  disabled={email.trim().length === 0}
                  label={t("sendResetCode")}
                  loading={busy}
                  onPress={() => void sendResetCode()}
                />
              ) : (
                <>
                  <Field
                    autoCapitalize="none"
                    autoComplete="one-time-code"
                    keyboardType="number-pad"
                    label={t("verificationCodeLabel")}
                    maxLength={6}
                    onChangeText={(value) => setCode(value.replace(/\D/g, "").slice(0, 6))}
                    placeholder="000000"
                    returnKeyType="done"
                    textContentType="oneTimeCode"
                    value={code}
                  />
                  <Field
                    autoCapitalize="none"
                    autoComplete="new-password"
                    autoCorrect={false}
                    label={t("newPasswordLabel")}
                    onChangeText={setNewPassword}
                    placeholder="••••••••"
                    secureTextEntry
                    textContentType="newPassword"
                    value={newPassword}
                  />
                  <Field
                    autoCapitalize="none"
                    autoComplete="new-password"
                    autoCorrect={false}
                    label={t("confirmPasswordLabel")}
                    onChangeText={setConfirmPassword}
                    placeholder="••••••••"
                    secureTextEntry
                    textContentType="newPassword"
                    value={confirmPassword}
                  />
                  <Text style={styles.hint}>{t("passwordHint")}</Text>
                  <PrimaryButton
                    disabled={
                      code.length !== 6 ||
                      newPassword.length < 8 ||
                      confirmPassword.length === 0
                    }
                    label={t("saveNewPassword")}
                    loading={busy}
                    onPress={() => void submitReset()}
                  />
                  <Pressable
                    accessibilityRole="button"
                    disabled={busy || resendIn > 0}
                    onPress={() => void sendResetCode()}
                    style={({ pressed }) => [styles.link, pressed && styles.pressed]}
                  >
                    <Text
                      style={[
                        styles.linkText,
                        (busy || resendIn > 0) && styles.linkDisabled,
                      ]}
                    >
                      {resendLabel}
                    </Text>
                  </Pressable>
                  <DebugCode code={debugCode} />
                </>
              )}
            </>
          ) : null}
        </View>

        <View style={styles.privacy}>
          <Ionicons name="lock-closed-outline" size={16} color={colors.primary} />
          <Text style={styles.privacyText}>{t("loginPrivacy")}</Text>
        </View>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

function safeNextPath(value: string | string[] | undefined): string {
  const raw = Array.isArray(value) ? value[0] : value;
  if (!raw) return "/";
  if (!raw.startsWith("/") || raw.startsWith("//")) return "/";
  if (raw === "/login" || raw.startsWith("/login?") || raw.startsWith("/login/")) {
    return "/";
  }
  return raw;
}

function Notice({ text }: { text: string }) {
  return (
    <View style={styles.notice}>
      <Ionicons name="checkmark-circle-outline" size={18} color={colors.primary} />
      <Text style={styles.noticeText}>{text}</Text>
    </View>
  );
}

function ErrorBox({ text }: { text: string }) {
  return (
    <View style={styles.errorBox}>
      <Ionicons name="alert-circle-outline" size={18} color={colors.danger} />
      <Text style={styles.errorText}>{text}</Text>
    </View>
  );
}

function DebugCode({ code }: { code: string | null }) {
  if (!__DEV__ || !code) return null;
  return (
    <View style={styles.debug}>
      <Text style={styles.debugLabel}>Development code</Text>
      <Text selectable style={styles.debugCode}>
        {code}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.background },
  brandRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  brandMark: {
    width: 30,
    height: 30,
    borderRadius: 10,
    backgroundColor: colors.primarySoft,
    alignItems: "center",
    justifyContent: "center",
  },
  brandText: {
    color: colors.primary,
    fontSize: type.tiny,
    fontWeight: "900",
    letterSpacing: 1.5,
  },
  hero: { gap: spacing.sm },
  eyebrow: {
    color: colors.accent,
    fontSize: 10,
    fontWeight: "900",
    letterSpacing: 1.4,
  },
  title: {
    color: colors.ink,
    fontSize: type.display,
    fontWeight: "900",
    letterSpacing: -0.8,
  },
  subtitle: { color: colors.inkMuted, fontSize: type.body, lineHeight: 22 },
  localeCard: {
    backgroundColor: colors.surface,
    borderRadius: radii.md,
    borderWidth: 1,
    borderColor: colors.line,
    padding: spacing.md,
    gap: spacing.sm,
  },
  localeHeader: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  localeLabel: { color: colors.ink, fontSize: type.small, fontWeight: "800" },
  localeRow: { flexDirection: "row", gap: spacing.sm },
  localeButton: {
    flex: 1,
    minHeight: 40,
    borderRadius: radii.sm,
    borderWidth: 1,
    borderColor: colors.line,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.background,
  },
  localeButtonActive: {
    borderColor: colors.primary,
    backgroundColor: colors.primarySoft,
  },
  localeButtonText: { color: colors.ink, fontSize: type.small, fontWeight: "700" },
  localeButtonTextActive: { color: colors.primary },
  segment: {
    flexDirection: "row",
    backgroundColor: colors.surfaceMuted,
    borderRadius: radii.pill,
    padding: 4,
    gap: 4,
  },
  segmentButton: {
    flex: 1,
    minHeight: 40,
    borderRadius: radii.pill,
    alignItems: "center",
    justifyContent: "center",
  },
  segmentButtonActive: { backgroundColor: colors.surface },
  segmentLabel: { color: colors.inkMuted, fontSize: type.small, fontWeight: "800" },
  segmentLabelActive: { color: colors.primary },
  backLink: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.xs,
    minHeight: 40,
  },
  backLinkText: { color: colors.primary, fontSize: type.small, fontWeight: "800" },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radii.lg,
    borderWidth: 1,
    borderColor: colors.line,
    padding: spacing.lg,
    gap: spacing.md,
  },
  cardTitle: { color: colors.ink, fontSize: type.heading, fontWeight: "900" },
  cardBody: { color: colors.inkMuted, fontSize: type.small, lineHeight: 19 },
  hint: { color: colors.inkMuted, fontSize: type.tiny, lineHeight: 17 },
  link: { minHeight: 40, alignItems: "center", justifyContent: "center" },
  linkText: { color: colors.primary, fontSize: type.small, fontWeight: "800" },
  linkDisabled: { color: colors.inkMuted },
  pressed: { opacity: 0.82 },
  notice: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: spacing.sm,
    backgroundColor: colors.primarySoft,
    borderRadius: radii.md,
    padding: spacing.md,
  },
  noticeText: { flex: 1, color: colors.ink, fontSize: type.small, lineHeight: 19 },
  errorBox: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: spacing.sm,
    backgroundColor: colors.dangerSoft,
    borderRadius: radii.md,
    padding: spacing.md,
  },
  errorText: { flex: 1, color: colors.danger, fontSize: type.small, lineHeight: 19 },
  debug: {
    backgroundColor: colors.primarySoft,
    borderRadius: radii.md,
    padding: spacing.md,
    gap: 2,
  },
  debugLabel: { color: colors.inkMuted, fontSize: type.tiny, fontWeight: "700" },
  debugCode: {
    color: colors.ink,
    fontSize: type.heading,
    fontWeight: "900",
    letterSpacing: 3,
  },
  privacy: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: spacing.sm,
    paddingHorizontal: spacing.xs,
  },
  privacyText: { flex: 1, color: colors.inkMuted, fontSize: type.small, lineHeight: 19 },
});
