import { Ionicons } from "@expo/vector-icons";
import { ActivityIndicator, StyleSheet, Text, View } from "react-native";

import { colors, spacing, type } from "../theme";
import { PrimaryButton } from "./PrimaryButton";

export function LoadingState({ label = "Loading…" }: { label?: string }) {
  return (
    <View style={styles.wrap}>
      <ActivityIndicator color={colors.primary} />
      <Text style={styles.text}>{label}</Text>
    </View>
  );
}

export function ErrorState({
  message,
  onRetry,
}: {
  message: string;
  onRetry?: () => void;
}) {
  return (
    <View style={styles.wrap}>
      <Ionicons name="alert-circle-outline" size={30} color={colors.danger} />
      <Text style={styles.errorText}>{message}</Text>
      {onRetry ? (
        <PrimaryButton label="Try again" onPress={onRetry} variant="secondary" style={styles.retry} />
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    alignItems: "center",
    paddingVertical: spacing.xxl,
    paddingHorizontal: spacing.xl,
    gap: spacing.sm,
  },
  text: {
    color: colors.inkMuted,
    fontSize: type.body,
  },
  errorText: {
    color: colors.danger,
    fontSize: type.body,
    lineHeight: 22,
    textAlign: "center",
  },
  retry: {
    marginTop: spacing.md,
    alignSelf: "stretch",
  },
});
