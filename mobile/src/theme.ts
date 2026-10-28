export const colors = {
  background: "#F5F0E6",
  surface: "#FFFDF8",
  surfaceMuted: "#EDE6D9",
  ink: "#1B211D",
  inkMuted: "#626A63",
  line: "#DDD4C5",
  primary: "#1E6A57",
  primaryPressed: "#155242",
  primarySoft: "#DCEBE4",
  accent: "#C76B2B",
  accentSoft: "#F6E4D6",
  danger: "#A33A32",
  dangerSoft: "#F5E0DD",
  success: "#2F7553",
  successSoft: "#DDEEE3",
  white: "#FFFFFF",
  overlay: "rgba(27, 33, 29, 0.45)",
} as const;

export const radii = {
  sm: 8,
  md: 14,
  lg: 20,
  pill: 999,
} as const;

export const spacing = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 18,
  xl: 24,
  xxl: 32,
} as const;

export const type = {
  display: 32,
  title: 24,
  heading: 19,
  body: 15,
  small: 13,
  tiny: 11,
} as const;

export const shadow = {
  card: {
    shadowColor: "#1B211D",
    shadowOffset: { width: 0, height: 3 },
    shadowOpacity: 0.08,
    shadowRadius: 10,
    elevation: 2,
  },
} as const;
