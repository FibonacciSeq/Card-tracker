import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ApiError } from "../api/client";
import {
  useCompleteReservation,
  useReservation,
  useReservations,
  useUpdateReservationStatus,
} from "../api/queries";
import { NEXT_STATUS, type CompleteLine, type StaffReservation } from "../api/types";
import { StatusBadge } from "../components/StatusBadge";
import { describeRemaining, formatDateTime, formatMoney } from "../lib/format";
import { useLocale } from "../state/locale";

const FILTERS = ["ALL", "REQUESTED", "CONFIRMED", "READY", "COMPLETED", "CANCELLED", "EXPIRED"] as const;

export function ReservationsPage() {
  const { t } = useLocale();
  const [params, setParams] = useSearchParams();
  const status = params.get("status") ?? "ALL";
  const [selected, setSelected] = useState<string | null>(null);
  const { data, isPending, error, refetch, isFetching } = useReservations(status);

  const reservations = data ?? [];
  const filterLabels: Record<string, string> = {
    ALL: t("All"),
    REQUESTED: t("Requested"),
    CONFIRMED: t("Confirmed"),
    READY: t("Ready"),
    COMPLETED: t("Completed"),
    CANCELLED: t("Cancelled"),
    EXPIRED: t("Expired"),
  };
  const statusLabel = filterLabels[status] ?? status.toLowerCase();

  return (
    <div className="page">
      <header className="page__header">
        <div>
          <h1>{t("Reservations")}</h1>
          <p className="muted">{t("Holds start when the customer submits and release on cancel or expiry.")}</p>
        </div>
        <button type="button" className="btn btn--ghost" onClick={() => void refetch()} disabled={isFetching}>
          {isFetching ? t("Refreshing…") : t("Refresh")}
        </button>
      </header>

      <div className="tabs" role="tablist" aria-label={t("Filter by status")}>
        {FILTERS.map((filter) => (
          <button
            key={filter}
            type="button"
            role="tab"
            aria-selected={status === filter}
            className={`tab${status === filter ? " tab--active" : ""}`}
            onClick={() => {
              setSelected(null);
              setParams(filter === "ALL" ? {} : { status: filter }, { replace: true });
            }}
          >
            {filterLabels[filter]}
          </button>
        ))}
      </div>

      {error ? (
        <p className="alert alert--error" role="alert">
          {t(error.message)}
        </p>
      ) : null}

      <div className={`split${selected ? " split--detail" : ""}`}>
        <div className="table-wrap">
          <table className="table" data-testid="reservations-table">
            <caption className="sr-only">{t("Reservation queue")}</caption>
            <thead>
              <tr>
                <th scope="col">{t("Reference")}</th>
                <th scope="col">{t("Customer")}</th>
                <th scope="col">{t("Status")}</th>
                <th scope="col">{t("Items")}</th>
                <th scope="col">{t("Total")}</th>
                <th scope="col">{t("Hold")}</th>
                <th scope="col">
                  <span className="sr-only">{t("Open")}</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {reservations.map((item) => {
                const remaining = describeRemaining(item.expires_at, t);
                const active = ["REQUESTED", "CONFIRMED", "READY"].includes(item.status);
                return (
                  <tr key={item.id} className={selected === item.id ? "row--selected" : undefined}>
                    <td>
                      <span className="mono">{item.public_ref}</span>
                      <div className="muted small">{formatDateTime(item.created_at)}</div>
                    </td>
                    <td>{item.customer_name}</td>
                    <td>
                      <StatusBadge status={item.status} />
                    </td>
                    <td className="num">{item.line_count}</td>
                    <td className="num">{formatMoney(item.total.amount_minor, item.total.currency)}</td>
                    <td className={active && remaining.overdue ? "tone--danger small" : "small muted"}>
                      {active ? remaining.label : "—"}
                    </td>
                    <td>
                      <button
                        type="button"
                        className="btn btn--small"
                        onClick={() => setSelected(selected === item.id ? null : item.id)}
                        aria-expanded={selected === item.id}
                      >
                        {selected === item.id ? t("Close") : t("Open")}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>

          {!isPending && reservations.length === 0 ? (
            <div className="empty">
              <h2>{t("Nothing here")}</h2>
              <p className="muted">
                {status === "ALL"
                  ? t("No reservations yet. New customer holds appear here immediately.")
                  : t("No {status} reservations.", { status: statusLabel })}
              </p>
            </div>
          ) : null}
        </div>

        {selected ? (
          <ReservationDetail id={selected} onClose={() => setSelected(null)} />
        ) : null}
      </div>
    </div>
  );
}

function ReservationDetail({ id, onClose }: { id: string; onClose: () => void }) {
  const { t } = useLocale();
  const { data, isPending, error } = useReservation(id);

  return (
    <aside className="detail" aria-label={t("Reservation details")} data-testid="reservation-detail">
      <div className="detail__header">
        <h2>{t("Reservation")}</h2>
        <button type="button" className="btn btn--ghost btn--small" onClick={onClose}>
          {t("Close")}
        </button>
      </div>

      {error ? (
        <p className="alert alert--error" role="alert">
          {t(error.message)}
        </p>
      ) : null}
      {isPending ? <p className="muted">{t("Loading…")}</p> : null}
      {data ? <ReservationBody key={data.id} reservation={data} /> : null}
    </aside>
  );
}

function ReservationBody({ reservation }: { reservation: StaffReservation }) {
  const { t } = useLocale();
  const updateStatus = useUpdateReservationStatus();
  const complete = useCompleteReservation();
  const [reason, setReason] = useState("");
  const [confirmCancel, setConfirmCancel] = useState(false);
  const [quantities, setQuantities] = useState<Record<string, { complete: string; cancel: string }>>(() =>
    Object.fromEntries(
      reservation.lines.map((line) => {
        const remaining = line.quantity - line.completed_quantity - line.cancelled_quantity;
        return [line.line_id, { complete: String(Math.max(remaining, 0)), cancel: "0" }];
      }),
    ),
  );

  const remaining = describeRemaining(reservation.expires_at, t);
  const allowed = NEXT_STATUS[reservation.status] ?? [];
  const active = ["REQUESTED", "CONFIRMED", "READY"].includes(reservation.status);
  const busy = updateStatus.isPending || complete.isPending;
  const failure = updateStatus.error ?? complete.error;

  const lines: CompleteLine[] = reservation.lines.flatMap((line) => {
    const entry = quantities[line.line_id] ?? { complete: "0", cancel: "0" };
    const completeQty = Math.max(0, Number(entry.complete) || 0);
    const cancelQty = Math.max(0, Number(entry.cancel) || 0);
    if (completeQty === 0 && cancelQty === 0) return [];
    return [{ line_id: line.line_id, complete_quantity: completeQty, cancel_quantity: cancelQty }];
  });

  const totalSelected = lines.reduce(
    (sum, line) => sum + (line.complete_quantity ?? 0) + (line.cancel_quantity ?? 0),
    0,
  );

  function setQuantity(lineId: string, field: "complete" | "cancel", value: string) {
    setQuantities((current) => ({
      ...current,
      [lineId]: { ...(current[lineId] ?? { complete: "0", cancel: "0" }), [field]: value },
    }));
  }

  return (
    <div className="detail__body">
      <div className="detail__meta">
        <div>
          <span className="muted small">{t("Reference")}</span>
          <div className="mono">{reservation.public_ref}</div>
        </div>
        <div>
          <span className="muted small">{t("Status")}</span>
          <div>
            <StatusBadge status={reservation.status} />
          </div>
        </div>
        <div>
          <span className="muted small">{t("Total")}</span>
          <div>
            {formatMoney(reservation.total.amount_minor, reservation.total.currency)}
          </div>
        </div>
        <div>
          <span className="muted small">{active ? t("Hold") : t("Expiry")}</span>
          <div className={active && remaining.overdue ? "tone--danger" : undefined}>
            {active ? remaining.label : formatDateTime(reservation.expires_at)}
          </div>
        </div>
      </div>

      <section aria-labelledby="customer-title">
        <h3 id="customer-title">{t("Customer")}</h3>
        <p>
          <strong>{reservation.customer_name}</strong>
        </p>
        <p className="small">
          <a href={`mailto:${reservation.customer_email}`}>{reservation.customer_email}</a>
          {reservation.customer_phone ? (
            <>
              {" · "}
              <a href={`tel:${reservation.customer_phone}`}>{reservation.customer_phone}</a>
            </>
          ) : null}
        </p>
        {reservation.note ? <p className="note">“{reservation.note}”</p> : null}
      </section>

      <section aria-labelledby="lines-title">
        <h3 id="lines-title">{t("Cards")}</h3>
        <table className="table table--tight">
          <thead>
            <tr>
              <th scope="col">{t("Card")}</th>
              <th scope="col" className="num">
                {t("Qty")}
              </th>
              <th scope="col" className="num">
                {t("Unit")}
              </th>
              <th scope="col" className="num">
                {t("Done")}
              </th>
            </tr>
          </thead>
          <tbody>
            {reservation.lines.map((line) => (
              <tr key={line.line_id}>
                <td>
                  <div className="card-cell">
                    {line.image_small ? (
                      <img
                        className="card-cell__thumb"
                        src={line.image_small}
                        alt=""
                        width={40}
                        height={56}
                        loading="lazy"
                      />
                    ) : (
                      <span className="card-cell__thumb card-cell__thumb--placeholder" aria-hidden="true" />
                    )}
                    <div>
                      <div>{line.name}</div>
                      <div className="muted small">
                        {line.set_code.toUpperCase()} #{line.collector_number} · {line.condition} · {line.finish}
                      </div>
                    </div>
                  </div>
                </td>
                <td className="num">{line.quantity}</td>
                <td className="num">{formatMoney(line.unit_price.amount_minor, line.unit_price.currency)}</td>
                <td className="num">{line.completed_quantity}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {failure ? (
        <p className="alert alert--error" role="alert">
          {failure instanceof ApiError ? t(failure.message) : String(failure)}
        </p>
      ) : null}

      {active ? (
        <>
          <section aria-labelledby="actions-title">
            <h3 id="actions-title">{t("Next step")}</h3>
            <div className="button-row">
              {allowed
                .filter((next) => next !== "CANCELLED")
                .map((next) => (
                  <button
                    key={next}
                    type="button"
                    className={`btn ${next === "READY" ? "btn--primary" : ""}`}
                    disabled={busy}
                    onClick={() => updateStatus.mutate({ id: reservation.id, status: next })}
                  >
                    {next === "CONFIRMED" ? t("Confirm request") : t("Mark ready for pickup")}
                  </button>
                ))}
              <button
                type="button"
                className="btn btn--danger"
                disabled={busy}
                onClick={() => setConfirmCancel((open) => !open)}
              >
                {t("Cancel reservation")}
              </button>
            </div>

            {confirmCancel ? (
              <div className="confirm">
                <div className="field">
                  <label htmlFor="cancel-reason">{t("Reason (optional)")}</label>
                  <input
                    id="cancel-reason"
                    value={reason}
                    maxLength={2000}
                    onChange={(event) => setReason(event.target.value)}
                    placeholder={t("Customer changed their mind, cards damaged…")}
                  />
                </div>
                <div className="button-row">
                  <button
                    type="button"
                    className="btn btn--danger"
                    disabled={busy}
                    onClick={() =>
                      updateStatus.mutate(
                        { id: reservation.id, status: "CANCELLED", reason: reason || undefined },
                        { onSuccess: () => setConfirmCancel(false) },
                      )
                    }
                  >
                    {t("Confirm cancellation")}
                  </button>
                  <button type="button" className="btn btn--ghost" onClick={() => setConfirmCancel(false)}>
                    {t("Keep reservation")}
                  </button>
                </div>
                <p className="hint">{t("Cancelling releases the held stock immediately.")}</p>
              </div>
            ) : null}
          </section>

          <section aria-labelledby="complete-title">
            <h3 id="complete-title">{t("Complete at the counter")}</h3>
            <p className="muted small">
              {t(
                "Adjust quantities if the customer takes fewer cards. Completed copies become sales; cancelled ones return to stock.",
              )}
            </p>
            <table className="table table--tight">
              <thead>
                <tr>
                  <th scope="col">{t("Card")}</th>
                  <th scope="col">{t("Complete")}</th>
                  <th scope="col">{t("Cancel")}</th>
                </tr>
              </thead>
              <tbody>
                {reservation.lines.map((line) => {
                  const left = line.quantity - line.completed_quantity - line.cancelled_quantity;
                  const entry = quantities[line.line_id] ?? { complete: "0", cancel: "0" };
                  return (
                    <tr key={line.line_id}>
                      <td>
                        <div className="card-cell">
                          {line.image_small ? (
                            <img
                              className="card-cell__thumb"
                              src={line.image_small}
                              alt=""
                              width={40}
                              height={56}
                              loading="lazy"
                            />
                          ) : (
                            <span
                              className="card-cell__thumb card-cell__thumb--placeholder"
                              aria-hidden="true"
                            />
                          )}
                          <div>
                            {line.name}
                            <div className="muted small">{t("{count} still held", { count: left })}</div>
                          </div>
                        </div>
                      </td>
                      <td>
                        <input
                          aria-label={t("Copies of {name} to complete", { name: line.name })}
                          type="number"
                          min={0}
                          max={left}
                          value={entry.complete}
                          onChange={(event) => setQuantity(line.line_id, "complete", event.target.value)}
                        />
                      </td>
                      <td>
                        <input
                          aria-label={t("Copies of {name} to cancel", { name: line.name })}
                          type="number"
                          min={0}
                          max={left}
                          value={entry.cancel}
                          onChange={(event) => setQuantity(line.line_id, "cancel", event.target.value)}
                        />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <div className="button-row">
              <button
                type="button"
                className="btn btn--primary"
                disabled={busy || totalSelected === 0}
                onClick={() => complete.mutate({ id: reservation.id, body: { lines } })}
              >
                {busy ? t("Saving…") : t("Complete reservation")}
              </button>
              <span className="muted small">
                {totalSelected === 1
                  ? t("{count} copy selected", { count: totalSelected })
                  : t("{count} copies selected", { count: totalSelected })}
              </span>
            </div>
          </section>
        </>
      ) : (
        <p className="muted">{t("This reservation is closed. Stock effects are already applied.")}</p>
      )}
    </div>
  );
}
