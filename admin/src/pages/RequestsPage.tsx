import { Fragment, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ApiError } from "../api/client";
import {
  useCardRequests,
  useConvertCardRequest,
  useDeclineCardRequest,
  useQuoteCardRequest,
} from "../api/queries";
import type { StaffCardRequest } from "../api/types";
import { StatusBadge } from "../components/StatusBadge";
import { formatDateTime, formatMoney } from "../lib/format";

const FILTERS = [
  "ALL",
  "REQUESTED",
  "QUOTED",
  "ACCEPTED",
  "DECLINED",
  "CONVERTED",
  "CANCELLED",
  "EXPIRED",
] as const;

type Panel = { id: string; mode: "quote" | "decline" | "convert" } | null;

export function RequestsPage() {
  const [params, setParams] = useSearchParams();
  const status = params.get("status") ?? "ALL";
  const [panel, setPanel] = useState<Panel>(null);
  const { data, isPending, error, refetch, isFetching } = useCardRequests(status);

  const requests = data ?? [];
  const open = (item: StaffCardRequest, mode: NonNullable<Panel>["mode"]) =>
    setPanel(panel?.id === item.id && panel.mode === mode ? null : { id: item.id, mode });

  return (
    <div className="page">
      <header className="page__header">
        <div>
          <h1>Special orders</h1>
          <p className="muted">
            Customers ask, you quote, and the card becomes a normal reservation once it is back in stock.
          </p>
        </div>
        <button type="button" className="btn btn--ghost" onClick={() => void refetch()} disabled={isFetching}>
          {isFetching ? "Refreshing…" : "Refresh"}
        </button>
      </header>

      <div className="tabs" role="tablist" aria-label="Filter by status">
        {FILTERS.map((filter) => (
          <button
            key={filter}
            type="button"
            role="tab"
            aria-selected={status === filter}
            className={`tab${status === filter ? " tab--active" : ""}`}
            onClick={() => {
              setPanel(null);
              setParams(filter === "ALL" ? {} : { status: filter }, { replace: true });
            }}
          >
            {filter === "ALL" ? "All" : filter.charAt(0) + filter.slice(1).toLowerCase()}
          </button>
        ))}
      </div>

      {error ? (
        <p className="alert alert--error" role="alert">
          {error.message}
        </p>
      ) : null}

      <div className="table-wrap">
        <table className="table" data-testid="requests-table">
          <caption className="sr-only">Special-order requests</caption>
          <thead>
            <tr>
              <th scope="col">Reference</th>
              <th scope="col">Customer</th>
              <th scope="col">Card</th>
              <th scope="col">Qty</th>
              <th scope="col">Target</th>
              <th scope="col">Quote</th>
              <th scope="col">Status</th>
              <th scope="col">
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {requests.map((item) => {
              const expanded = panel?.id === item.id;
              return (
                <Fragment key={item.id}>
                  <tr className={expanded ? "row--open" : undefined} data-testid={`request-row-${item.public_ref}`}>
                    <td>
                      <span className="mono">{item.public_ref}</span>
                      <div className="muted small">{formatDateTime(item.created_at)}</div>
                    </td>
                    <td>
                      <div>{item.customer_name}</div>
                      <div className="muted small">{item.customer_email}</div>
                    </td>
                    <td>
                      <div>{item.requested_name}</div>
                      <div className="muted small">
                        {[
                          item.set_code.toUpperCase(),
                          item.collector_number ? `#${item.collector_number}` : "",
                          item.condition,
                          item.finish,
                          item.language,
                        ]
                          .filter(Boolean)
                          .join(" · ")}
                      </div>
                    </td>
                    <td className="num">{item.quantity}</td>
                    <td className="num">
                      {item.target_price
                        ? formatMoney(item.target_price.amount_minor, item.target_price.currency)
                        : "—"}
                    </td>
                    <td className="num">
                      {item.quote_price
                        ? formatMoney(item.quote_price.amount_minor, item.quote_price.currency)
                        : "—"}
                    </td>
                    <td>
                      <StatusBadge status={item.status} />
                    </td>
                    <td>
                      <div className="row-actions">
                        {["REQUESTED", "QUOTED"].includes(item.status) ? (
                          <>
                            <button
                              type="button"
                              className="btn btn--small"
                              onClick={() => open(item, "quote")}
                              aria-expanded={expanded && panel?.mode === "quote"}
                              data-testid={`quote-btn-${item.public_ref}`}
                            >
                              {item.status === "QUOTED" ? "Re-quote" : "Quote"}
                            </button>
                            <button
                              type="button"
                              className="btn btn--small btn--danger"
                              onClick={() => open(item, "decline")}
                              aria-expanded={expanded && panel?.mode === "decline"}
                              data-testid={`decline-btn-${item.public_ref}`}
                            >
                              Decline
                            </button>
                          </>
                        ) : null}
                        {item.status === "ACCEPTED" ? (
                          <button
                            type="button"
                            className="btn btn--small btn--primary"
                            onClick={() => open(item, "convert")}
                            aria-expanded={expanded && panel?.mode === "convert"}
                            data-testid={`convert-btn-${item.public_ref}`}
                          >
                            Convert to reservation
                          </button>
                        ) : null}
                        {item.reservation_ref ? (
                          <span className="muted small nowrap">Reservation {item.reservation_ref}</span>
                        ) : null}
                      </div>
                    </td>
                  </tr>
                  {expanded ? (
                    <tr>
                      <td colSpan={8} className="row-editor">
                        <RequestPanel item={item} mode={panel.mode} onClose={() => setPanel(null)} />
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              );
            })}
          </tbody>
        </table>

        {!isPending && requests.length === 0 ? (
          <div className="empty">
            <h2>Nothing here</h2>
            <p className="muted">
              {status === "ALL"
                ? "No special orders yet. Requests from the customer app appear here."
                : `No ${status.toLowerCase()} requests.`}
            </p>
          </div>
        ) : null}
      </div>

      <p className="hint">
        No stock is held while a card is being sourced. Converting requires the exact card, finish, condition, and
        language to be in stock.
      </p>
    </div>
  );
}

function RequestPanel({
  item,
  mode,
  onClose,
}: {
  item: StaffCardRequest;
  mode: "quote" | "decline" | "convert";
  onClose: () => void;
}) {
  return (
    <div className="editor">
      <div className="detail__header">
        <h3>
          {mode === "quote" ? "Quote" : mode === "decline" ? "Decline" : "Convert"} {item.public_ref}
        </h3>
        <button type="button" className="btn btn--ghost btn--small" onClick={onClose}>
          Close
        </button>
      </div>

      {item.customer_note ? <p className="note">“{item.customer_note}”</p> : null}
      {item.vendor_note ? <p className="muted small">Previous note: {item.vendor_note}</p> : null}

      {mode === "quote" ? <QuoteForm item={item} onDone={onClose} /> : null}
      {mode === "decline" ? <DeclineForm item={item} onDone={onClose} /> : null}
      {mode === "convert" ? <ConvertForm item={item} onDone={onClose} /> : null}
    </div>
  );
}

function failureText(cause: unknown): string | null {
  if (!cause) return null;
  return cause instanceof ApiError ? cause.message : String(cause);
}

function QuoteForm({ item, onDone }: { item: StaffCardRequest; onDone: () => void }) {
  const quote = useQuoteCardRequest();
  const initial =
    item.quote_price?.amount_minor ??
    item.target_price?.amount_minor ??
    null;
  const [price, setPrice] = useState(initial !== null ? (initial / 100).toFixed(2) : "");
  const [expires, setExpires] = useState("");
  const [note, setNote] = useState(item.vendor_note ?? "");

  const minor = Math.round(Number(price) * 100);
  const valid = price.trim() !== "" && Number.isFinite(minor) && minor >= 0;

  return (
    <form
      className="form"
      onSubmit={(event) => {
        event.preventDefault();
        if (!valid) return;
        quote.mutate(
          {
            id: item.id,
            body: {
              quote_price_minor: minor,
              quote_expires_at: expires ? new Date(expires).toISOString() : null,
              vendor_note: note,
            },
          },
          { onSuccess: onDone },
        );
      }}
    >
      <div className="field-row">
        <div className="field">
          <label htmlFor={`quote-price-${item.id}`}>Quote price</label>
          <input
            id={`quote-price-${item.id}`}
            type="number"
            min={0}
            step="0.01"
            value={price}
            onChange={(event) => setPrice(event.target.value)}
            data-testid="quote-price"
            required
          />
          <span className="hint">Shown to the customer in the shop currency.</span>
        </div>
        <div className="field">
          <label htmlFor={`quote-expires-${item.id}`}>Quote expires (optional)</label>
          <input
            id={`quote-expires-${item.id}`}
            type="datetime-local"
            value={expires}
            onChange={(event) => setExpires(event.target.value)}
          />
        </div>
      </div>
      <div className="field">
        <label htmlFor={`quote-note-${item.id}`}>Note for the customer</label>
        <textarea
          id={`quote-note-${item.id}`}
          value={note}
          onChange={(event) => setNote(event.target.value)}
          placeholder="For example: can have it by Friday."
        />
      </div>

      {failureText(quote.error) ? (
        <p className="alert alert--error" role="alert">
          {failureText(quote.error)}
        </p>
      ) : null}

      <div className="form__footer">
        <button
          type="submit"
          className="btn btn--primary"
          disabled={!valid || quote.isPending}
          data-testid="quote-submit"
        >
          {quote.isPending ? "Sending…" : "Send quote"}
        </button>
        <span className="hint">The customer is emailed and can accept or cancel the quote.</span>
      </div>
    </form>
  );
}

function DeclineForm({ item, onDone }: { item: StaffCardRequest; onDone: () => void }) {
  const decline = useDeclineCardRequest();
  const [note, setNote] = useState("");

  return (
    <form
      className="form"
      onSubmit={(event) => {
        event.preventDefault();
        decline.mutate({ id: item.id, body: { vendor_note: note } }, { onSuccess: onDone });
      }}
    >
      <div className="field">
        <label htmlFor={`decline-note-${item.id}`}>Reason (optional)</label>
        <textarea
          id={`decline-note-${item.id}`}
          value={note}
          onChange={(event) => setNote(event.target.value)}
          placeholder="For example: out of print and cannot source a clean copy."
        />
      </div>

      {failureText(decline.error) ? (
        <p className="alert alert--error" role="alert">
          {failureText(decline.error)}
        </p>
      ) : null}

      <div className="form__footer">
        <button type="submit" className="btn btn--danger" disabled={decline.isPending} data-testid="decline-submit">
          {decline.isPending ? "Declining…" : "Decline request"}
        </button>
      </div>
    </form>
  );
}

function ConvertForm({ item, onDone }: { item: StaffCardRequest; onDone: () => void }) {
  const convert = useConvertCardRequest();
  const [quantity, setQuantity] = useState(String(item.quantity));
  const value = Number(quantity);
  const valid = Number.isInteger(value) && value >= 1 && value <= 999;

  return (
    <form
      className="form"
      onSubmit={(event) => {
        event.preventDefault();
        if (!valid) return;
        convert.mutate(
          { id: item.id, body: { quantity: value } },
          { onSuccess: onDone },
        );
      }}
    >
      <p className="muted">
        This creates a confirmed reservation for {item.customer_name} and holds the copies immediately.
      </p>
      <div className="inline-form">
        <label htmlFor={`convert-qty-${item.id}`}>Copies to hold</label>
        <input
          id={`convert-qty-${item.id}`}
          type="number"
          min={1}
          max={999}
          value={quantity}
          onChange={(event) => setQuantity(event.target.value)}
        />
      </div>

      {failureText(convert.error) ? (
        <p className="alert alert--error" role="alert">
          {failureText(convert.error)}
        </p>
      ) : null}

      <div className="form__footer">
        <button
          type="submit"
          className="btn btn--primary"
          disabled={!valid || convert.isPending}
          data-testid="convert-submit"
        >
          {convert.isPending ? "Converting…" : "Create reservation"}
        </button>
        <span className="hint">
          The card must already be in stock for the same variant; the hold uses the current shelf price.
        </span>
      </div>
    </form>
  );
}
