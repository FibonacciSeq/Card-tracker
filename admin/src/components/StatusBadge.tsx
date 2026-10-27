import type { ReservationStatus } from "../api/types";

const LABELS: Record<string, string> = {
  REQUESTED: "Requested",
  CONFIRMED: "Confirmed",
  READY: "Ready",
  COMPLETED: "Completed",
  CANCELLED: "Cancelled",
  EXPIRED: "Expired",
};

/** Colour is never the only signal: every badge also prints its label. */
export function StatusBadge({ status }: { status: ReservationStatus | string }) {
  const tone = status.toLowerCase();
  return (
    <span className={`badge badge--${tone}`}>
      <span aria-hidden="true" className="badge__dot" />
      {LABELS[status] ?? status}
    </span>
  );
}
