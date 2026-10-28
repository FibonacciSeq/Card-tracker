import type { Money } from "../api/types";

export function formatMoney(money: Money | null | undefined): string {
  if (!money) return "—";
  const amount = money.amount_minor / 100;
  try {
    return new Intl.NumberFormat(undefined, {
      style: "currency",
      currency: money.currency,
    }).format(amount);
  } catch {
    return `${money.currency} ${amount.toFixed(2)}`;
  }
}

export function formatDateTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

export function formatRemaining(value: string, now = Date.now()): string {
  const end = new Date(value).getTime();
  if (Number.isNaN(end)) return "";
  const diff = end - now;
  if (diff <= 0) return "Expired";
  const minutes = Math.floor(diff / 60_000);
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `${hours} h ${minutes % 60} min`;
  return `${Math.floor(hours / 24)} days`;
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
      return "accent";
    case "CANCELLED":
    case "EXPIRED":
      return "danger";
    default:
      return "muted";
  }
}
