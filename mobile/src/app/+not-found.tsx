import { useRouter } from "expo-router";
import { StyleSheet, Text, View } from "react-native";

import { PrimaryButton } from "../components/PrimaryButton";
import { colors, spacing, type } from "../theme";

export default function NotFoundScreen() {
  const router = useRouter();
  return (
    <View style={styles.wrap}>
      <Text style={styles.code}>404</Text>
      <Text style={styles.title}>This shelf is empty.</Text>
      <Text style={styles.body}>That screen does not exist. Head back to the shop directory.</Text>
      <PrimaryButton label="Go home" onPress={() => router.replace("/")} style={styles.button} />
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    flex: 1,
    backgroundColor: colors.background,
    alignItems: "center",
    justifyContent: "center",
    padding: spacing.xl,
    gap: spacing.sm,
  },
  code: {
    color: colors.accent,
    fontSize: 64,
    fontWeight: "900",
    letterSpacing: -3,
  },
  title: {
    color: colors.ink,
    fontSize: type.title,
    fontWeight: "900",
    textAlign: "center",
  },
  body: {
    color: colors.inkMuted,
    fontSize: type.body,
    lineHeight: 22,
    textAlign: "center",
  },
  button: {
    alignSelf: "stretch",
    marginTop: spacing.lg,
  },
});
