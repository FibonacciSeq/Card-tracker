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

/** Human countdown used on reservation holds. Negative values mean overdue. */
export function describeRemaining(expiresAt: string): { label: string; overdue: boolean } {
  const ms = new Date(expiresAt).getTime() - Date.now();
  const overdue = ms <= 0;
  const minutes = Math.round(Math.abs(ms) / 60_000);
  const hours = Math.floor(minutes / 60);
  const label =
    hours >= 1 ? `${hours}h ${minutes % 60}m` : `${Math.max(minutes, 1)}m`;
  return { label: overdue ? `expired ${label} ago` : `${label} left`, overdue };
}

export function percent(part: number, whole: number): number {
  if (whole <= 0) return 0;
  return Math.round((part / whole) * 100);
}
