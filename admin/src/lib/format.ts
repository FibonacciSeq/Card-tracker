export function formatMoney(amountMinor: number, currency: string): string {
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
  }).format(amountMinor / 100);
}

export function formatDateTime(value: string | Date): string {
  const date = typeof value === "string" ? new Date(value) : value;
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(date);
}

type Translator = (key: string, params?: Record<string, string | number>) => string;

/** English interpolation for callers without a locale translator. */
const english: Translator = (key, params) =>
  params ? key.replace(/\{(\w+)\}/g, (_, name: string) => String(params[name] ?? `{${name}}`)) : key;

/** Human countdown used on reservation holds. Negative values mean overdue. */
export function describeRemaining(expiresAt: string, t: Translator = english): { label: string; overdue: boolean } {
  const ms = new Date(expiresAt).getTime() - Date.now();
  const overdue = ms <= 0;
  const minutes = Math.round(Math.abs(ms) / 60_000);
  const hours = Math.floor(minutes / 60);
  const label =
    hours >= 1
      ? t("{hours}h {minutes}m", { hours, minutes: minutes % 60 })
      : t("{count}m", { count: Math.max(minutes, 1) });
  return { label: overdue ? t("expired {time} ago", { time: label }) : t("{time} left", { time: label }), overdue };
}

export function percent(part: number, whole: number): number {
  if (whole <= 0) return 0;
  return Math.round((part / whole) * 100);
}
