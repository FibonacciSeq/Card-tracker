import { useState } from "react";
import { ApiError } from "../api/client";
import { useAudit } from "../api/queries";
import { formatDateTime } from "../lib/format";

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
  "stock.sell": "Sold in store",
  "stock.import": "CSV import",
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
  const { data, isPending, error } = useAudit(filter);

  return (
    <div className="page">
      <header className="page__header">
        <div>
          <h1>Activity</h1>
          <p className="muted">A record of who changed what, newest first. Entries cannot be edited.</p>
        </div>
        <label className="field field--inline">
          <span>Show</span>
          <select value={filter} onChange={(event) => setFilter(event.target.value)} data-testid="activity-filter">
            {FILTERS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      </header>

      {error ? (
        <p className="alert alert--error" role="alert">
          {error instanceof ApiError ? error.message : "Could not load activity."}
        </p>
      ) : null}

      {isPending ? <p className="muted">Loading…</p> : null}

      {data && data.length === 0 ? (
        <div className="card">
          <p className="muted">Nothing recorded yet. Stock and reservation changes will appear here.</p>
        </div>
      ) : null}

      {data && data.length > 0 ? (
        <div className="table-wrap">
          <table className="table" data-testid="activity-table">
            <caption className="sr-only">Audit trail</caption>
            <thead>
              <tr>
                <th scope="col">When</th>
                <th scope="col">Who</th>
                <th scope="col">Action</th>
                <th scope="col">Details</th>
              </tr>
            </thead>
            <tbody>
              {data.map((event) => {
                const group = event.action.split(".")[0] ?? "";
                return (
                  <tr key={event.id}>
                    <td className="nowrap">{formatDateTime(event.created_at)}</td>
                    <td>{event.actor_email ?? "Customer"}</td>
                    <td>
                      <span className={`badge ${ACTION_TONES[group] ?? ""}`}>
                        <span aria-hidden="true" className="badge__dot" />
                        {ACTION_LABELS[event.action] ?? event.action}
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
