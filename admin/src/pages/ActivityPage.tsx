import { useState } from "react";
import { ApiError } from "../api/client";
import { useAudit } from "../api/queries";
import { formatDateTime } from "../lib/format";
import { useLocale } from "../state/locale";

const FILTERS = [
  { value: "", label: "All activity" },
  { value: "stock", label: "Stock" },
  { value: "reservation", label: "Reservations" },
  { value: "settings", label: "Settings" },
  { value: "staff", label: "Team" },
];

const ACTION_LABELS: Record<string, string> = {
  "stock.create": "Card added",
  "stock.update": "Stock changed",
  "stock.adjust": "Stock adjusted",
  "stock.confirm": "Stock confirmed",
  "stock.sell": "Sold in store",
  "stock.import": "CSV import",
  "stock.archive_all": "Stock archived",
  "stock.restore": "Stock restored",
  "stock.delete": "Archived card deleted",
  "stock.delete_all": "Archive deleted",
  "stock.delete_expired": "Expired archive cleaned",
  "reservation.status": "Reservation updated",
  "reservation.complete": "Reservation completed",
  "settings.update": "Settings changed",
  "staff.create": "Team member added",
  "staff.update": "Team member changed",
};

const ACTION_TONES: Record<string, string> = {
  stock: "badge--confirmed",
  reservation: "badge--ready",
  settings: "badge--requested",
  staff: "badge--completed",
};

export function ActivityPage() {
  const [filter, setFilter] = useState("");
  const { t } = useLocale();
  const { data, isPending, error } = useAudit(filter);

  return (
    <div className="page">
      <header className="page__header">
        <div>
          <h1>{t("Activity")}</h1>
          <p className="muted">{t("A record of who changed what, newest first. Entries cannot be edited.")}</p>
        </div>
        <label className="field field--inline">
          <span>{t("Show")}</span>
          <select value={filter} onChange={(event) => setFilter(event.target.value)} data-testid="activity-filter">
            {FILTERS.map((option) => (
              <option key={option.value} value={option.value}>
                {t(option.label)}
              </option>
            ))}
          </select>
        </label>
      </header>

      {error ? (
        <p className="alert alert--error" role="alert">
          {error instanceof ApiError ? t(error.message) : t("Could not load activity.")}
        </p>
      ) : null}

      {isPending ? <p className="muted">{t("Loading…")}</p> : null}

      {data && data.length === 0 ? (
        <div className="card">
          <p className="muted">{t("Nothing recorded yet. Stock and reservation changes will appear here.")}</p>
        </div>
      ) : null}

      {data && data.length > 0 ? (
        <div className="table-wrap">
          <table className="table" data-testid="activity-table">
            <caption className="sr-only">{t("Audit trail")}</caption>
            <thead>
              <tr>
                <th scope="col">{t("When")}</th>
                <th scope="col">{t("Who")}</th>
                <th scope="col">{t("Action")}</th>
                <th scope="col">{t("Details")}</th>
              </tr>
            </thead>
            <tbody>
              {data.map((event) => {
                const group = event.action.split(".")[0] ?? "";
                return (
                  <tr key={event.id}>
                    <td className="nowrap">{formatDateTime(event.created_at)}</td>
                    <td>{event.actor_email ?? t("Customer")}</td>
                    <td>
                      <span className={`badge ${ACTION_TONES[group] ?? ""}`}>
                        <span aria-hidden="true" className="badge__dot" />
                        {t(ACTION_LABELS[event.action] ?? event.action)}
                      </span>
                    </td>
                    <td>{event.summary}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}
