import type { ReservationStatus } from "../api/types";
import { useLocale } from "../state/locale";

/** Colour is never the only signal: every badge also prints its label. */
export function StatusBadge({ status }: { status: ReservationStatus | string }) {
  const { t } = useLocale();
  const LABELS: Record<string, string> = {
    REQUESTED: t("Requested"),
    QUOTED: t("Quoted"),
    ACCEPTED: t("Accepted"),
    DECLINED: t("Declined"),
    CONVERTED: t("Converted"),
    CONFIRMED: t("Confirmed"),
    READY: t("Ready"),
    COMPLETED: t("Completed"),
    CANCELLED: t("Cancelled"),
    EXPIRED: t("Expired"),
  };
  const tone = status.toLowerCase();
  return (
    <span className={`badge badge--${tone}`}>
      <span aria-hidden="true" className="badge__dot" />
      {LABELS[status] ?? status}
    </span>
  );
}
