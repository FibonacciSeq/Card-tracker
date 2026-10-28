import { Ionicons } from "@expo/vector-icons";
import { Pressable, ScrollView, StyleSheet, Text } from "react-native";

import type { StockSort } from "../api/types";
import { colors, radii, spacing, type } from "../theme";

const SORTS: { value: StockSort; label: string }[] = [
  { value: "relevance", label: "Best match" },
  { value: "name", label: "Name" },
  { value: "price_asc", label: "Price ↑" },
  { value: "price_desc", label: "Price ↓" },
  { value: "newest", label: "Newest" },
];

export function SortBar({
  value,
  onChange,
  availableOnly,
  onToggleAvailable,
}: {
  value: StockSort;
  onChange: (sort: StockSort) => void;
  availableOnly: boolean;
  onToggleAvailable: () => void;
}) {
  return (
    <ScrollView
      horizontal
      showsHorizontalScrollIndicator={false}
      contentContainerStyle={styles.content}
    >
      {SORTS.map((option) => (
        <Pressable
          accessibilityRole="button"
          key={option.value}
          onPress={() => onChange(option.value)}
          style={[styles.chip, value === option.value && styles.activeChip]}
        >
          <Text style={[styles.label, value === option.value && styles.activeLabel]}>
            {option.label}
          </Text>
        </Pressable>
      ))}
      <Pressable
        accessibilityRole="button"
        accessibilityState={{ selected: availableOnly }}
        onPress={onToggleAvailable}
        style={[styles.chip, availableOnly && styles.activeChip]}
      >
        <Ionicons
          name={availableOnly ? "checkmark-circle" : "ellipse-outline"}
          size={14}
          color={availableOnly ? colors.white : colors.inkMuted}
        />
        <Text style={[styles.label, availableOnly && styles.activeLabel]}>Available</Text>
      </Pressable>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  content: {
    gap: spacing.sm,
    paddingVertical: spacing.xs,
  },
  chip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 5,
    borderWidth: 1,
    borderColor: colors.line,
    backgroundColor: colors.surface,
    borderRadius: radii.pill,
    paddingHorizontal: spacing.md,
    paddingVertical: 7,
  },
  activeChip: {
    backgroundColor: colors.primary,
    borderColor: colors.primary,
  },
  label: {
    color: colors.inkMuted,
    fontSize: type.small,
    fontWeight: "700",
  },
  activeLabel: { color: colors.white },
});
