import type { Money } from "../api/types";
import { DEFAULT_LOCALE, getText } from "./locale";

type TimeFormatPreference = "auto" | "12h" | "24h";

type DateTimeFormatOptions = {
  locale?: string;
  timeFormat?: TimeFormatPreference;
};

function hourCycleFor(timeFormat: TimeFormatPreference | undefined): "h12" | "h23" | undefined {
  if (timeFormat === "12h") return "h12";
  if (timeFormat === "24h") return "h23";
  return undefined;
}

export function formatMoney(money: Money | null | undefined, locale?: string): string {
  if (!money) return "—";
  const amount = money.amount_minor / 100;
  try {
    return new Intl.NumberFormat(locale, {
      style: "currency",
      currency: money.currency,
    }).format(amount);
  } catch {
    return `${money.currency} ${amount.toFixed(2)}`;
  }
}

export function formatDateTime(value: string, options: DateTimeFormatOptions = {}): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(options.locale, {
    dateStyle: "medium",
    timeStyle: "short",
    hourCycle: hourCycleFor(options.timeFormat),
  }).format(date);
}

export function formatRemaining(
  value: string,
  now = Date.now(),
  t: (key: string, params?: Record<string, string | number>) => string = (key, params) =>
    getText(DEFAULT_LOCALE, key, params),
): string {
  const end = new Date(value).getTime();
  if (Number.isNaN(end)) return "";
  const diff = end - now;
  if (diff <= 0) return t("Expired");
  const minutes = Math.floor(diff / 60_000);
  if (minutes < 60) return t("{count} min", { count: minutes });
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return t("{hours} h {minutes} min", { hours, minutes: minutes % 60 });
  return t("{count} days", { count: Math.floor(hours / 24) });
}

export function titleCase(value: string): string {
  return value
    .replace(/_/g, " ")
    .toLowerCase()
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

export function statusTone(status: string): "success" | "accent" | "muted" | "danger" {
  switch (status) {
    case "READY":
      return "success";
    case "REQUESTED":
    case "CONFIRMED":
    case "QUOTED":
      return "accent";
    case "ACCEPTED":
    case "CONVERTED":
      return "success";
    case "CANCELLED":
    case "EXPIRED":
    case "DECLINED":
      return "danger";
    default:
      return "muted";
  }
}
