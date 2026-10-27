import { useState } from "react";
import { ApiError } from "../api/client";
import { useAdjustStock, useSellStock, useStock, useUpdateStock } from "../api/queries";
import type { StaffStock } from "../api/types";
import { StockLevels } from "../components/StockLevels";
import { formatDateTime, formatMoney } from "../lib/format";
import { useDebounced } from "../lib/useDebounced";

export function StockPage() {
  const [search, setSearch] = useState("");
  const [onlyOnline, setOnlyOnline] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  const query = useDebounced(search.trim());
  const { data, isPending, error, refetch, isFetching } = useStock(query, onlyOnline);

  const items = data?.items ?? [];

  return (
    <div className="page">
      <header className="page__header">
        <div>
          <h1>Stock</h1>
          <p className="muted">Only online stock is visible to customers in the app.</p>
        </div>
        <button type="button" className="btn btn--ghost" onClick={() => void refetch()} disabled={isFetching}>
          {isFetching ? "Refreshing…" : "Refresh"}
        </button>
      </header>

      <div className="toolbar">
        <div className="field field--inline">
          <label htmlFor="stock-search">Search cards</label>
          <input
            id="stock-search"
            type="search"
            placeholder="Card name, set, or collector number"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            data-testid="stock-search"
          />
        </div>
        <label className="checkbox">
          <input
            type="checkbox"
            checked={onlyOnline}
            onChange={(event) => setOnlyOnline(event.target.checked)}
          />
          Online only
        </label>
        <span className="muted small" aria-live="polite">
          {isPending ? "Loading…" : `${items.length} card${items.length === 1 ? "" : "s"}`}
        </span>
      </div>

      {error ? (
        <p className="alert alert--error" role="alert">
          {error.message}
        </p>
      ) : null}

      <div className="table-wrap">
        <table className="table" data-testid="stock-table">
          <caption className="sr-only">Stock with on-hand, reserved, and available counts</caption>
          <thead>
            <tr>
              <th scope="col">Card</th>
              <th scope="col">Availability</th>
              <th scope="col">Price</th>
              <th scope="col">Updated</th>
              <th scope="col">
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <StockRow
                key={item.stock_id}
                item={item}
                expanded={expanded === item.stock_id}
                onToggle={() => setExpanded(expanded === item.stock_id ? null : item.stock_id)}
              />
            ))}
          </tbody>
        </table>

        {!isPending && items.length === 0 ? (
          <div className="empty">
            <h2>No stock found</h2>
            <p className="muted">
              {query ? `Nothing matches “${query}”.` : "Add cards from the catalog to start selling them."}
            </p>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function StockRow({ item, expanded, onToggle }: { item: StaffStock; expanded: boolean; onToggle: () => void }) {
  return (
    <>
      <tr className={expanded ? "row--open" : undefined}>
        <td>
          <div className="card-cell">
            {item.card.image_small ? (
              <img
                className="card-cell__thumb"
                src={item.card.image_small}
                alt=""
                width={40}
                height={56}
                loading="lazy"
              />
            ) : (
              <span className="card-cell__thumb card-cell__thumb--placeholder" aria-hidden="true" />
            )}
            <div>
              <div className="card-cell__name">{item.card.name}</div>
              <div className="muted small">
                {item.card.set_code.toUpperCase()} #{item.card.collector_number} · {item.condition} ·{" "}
                {item.finish} · {item.language}
              </div>
              {!item.is_online ? <span className="badge badge--offline">Not online</span> : null}
            </div>
          </div>
        </td>
        <td>
          <StockLevels onHand={item.on_hand} reserved={item.reserved} available={item.available} />
        </td>
        <td className="num">{formatMoney(item.price.amount_minor, item.price.currency)}</td>
        <td className="muted small">{formatDateTime(item.updated_at)}</td>
        <td>
          <button type="button" className="btn btn--small" onClick={onToggle} aria-expanded={expanded}>
            {expanded ? "Close" : "Manage"}
          </button>
        </td>
      </tr>
      {expanded ? (
        <tr>
          <td colSpan={5} className="row-editor">
            <StockEditor item={item} onClose={onToggle} />
          </td>
        </tr>
      ) : null}
    </>
  );
}

function StockEditor({ item, onClose }: { item: StaffStock; onClose: () => void }) {
  const update = useUpdateStock();
  const adjust = useAdjustStock();
  const sell = useSellStock();

  const [quantity, setQuantity] = useState(String(item.on_hand));
  const [price, setPrice] = useState((item.price.amount_minor / 100).toFixed(2));
  const [delta, setDelta] = useState("1");
  const [reason, setReason] = useState("");
  const [saleQty, setSaleQty] = useState("1");
  const [notice, setNotice] = useState<string | null>(null);

  const busy = update.isPending || adjust.isPending || sell.isPending;
  const failure = update.error ?? adjust.error ?? sell.error;

  function errorText(cause: unknown): string {
    return cause instanceof ApiError ? cause.message : String(cause);
  }

  function saveStock(next: { quantity?: number; price_minor?: number; is_online?: boolean }, message: string) {
    setNotice(null);
    update.mutate(
      { id: item.stock_id, patch: next },
      { onSuccess: () => setNotice(message) },
    );
  }

  const priceMinor = Math.round(Number(price) * 100);
  const priceValid = Number.isFinite(priceMinor) && priceMinor >= 0 && price.trim() !== "";

  return (
    <div className="editor">
      <div className="editor__grid">
        <div className="editor__group">
          <h3>Counts</h3>
          <div className="inline-form">
            <label htmlFor={`qty-${item.stock_id}`}>On hand</label>
            <input
              id={`qty-${item.stock_id}`}
              type="number"
              min={0}
              value={quantity}
              onChange={(event) => setQuantity(event.target.value)}
            />
            <button
              type="button"
              className="btn btn--small"
              disabled={busy || quantity === ""}
              onClick={() => saveStock({ quantity: Number(quantity) }, "On-hand count saved.")}
            >
              Save
            </button>
          </div>
          <p className="hint">
            Cannot drop below the {item.reserved} reserved cop{item.reserved === 1 ? "y" : "ies"}. Use an adjustment
            for deliveries or shelf recounts so the ledger stays correct.
          </p>

          <div className="inline-form">
            <label htmlFor={`delta-${item.stock_id}`}>Adjust by</label>
            <input
              id={`delta-${item.stock_id}`}
              type="number"
              value={delta}
              onChange={(event) => setDelta(event.target.value)}
            />
            <button
              type="button"
              className="btn btn--small"
              disabled={busy || !Number(delta)}
              onClick={() =>
                adjust.mutate(
                  { id: item.stock_id, delta: Math.abs(Number(delta)), reason: reason || undefined },
                  { onSuccess: () => setNotice(`Added ${Math.abs(Number(delta))} to stock.`) },
                )
              }
            >
              Add
            </button>
            <button
              type="button"
              className="btn btn--small"
              disabled={busy || !Number(delta)}
              onClick={() =>
                adjust.mutate(
                  { id: item.stock_id, delta: -Math.abs(Number(delta)), reason: reason || undefined },
                  { onSuccess: () => setNotice(`Removed ${Math.abs(Number(delta))} from stock.`) },
                )
              }
            >
              Remove
            </button>
          </div>
        </div>

        <div className="editor__group">
          <h3>Price &amp; visibility</h3>
          <div className="inline-form">
            <label htmlFor={`price-${item.stock_id}`}>Price ({item.price.currency})</label>
            <input
              id={`price-${item.stock_id}`}
              inputMode="decimal"
              value={price}
              onChange={(event) => setPrice(event.target.value)}
            />
            <button
              type="button"
              className="btn btn--small"
              disabled={busy || !priceValid}
              onClick={() => saveStock({ price_minor: priceMinor }, "Price saved.")}
            >
              Save
            </button>
          </div>

          <label className="checkbox">
            <input
              type="checkbox"
              checked={item.is_online}
              disabled={busy}
              onChange={(event) =>
                saveStock(
                  { is_online: event.target.checked },
                  event.target.checked ? "Card is now visible to customers." : "Card hidden from the app.",
                )
              }
            />
            Visible in the customer app
          </label>
        </div>

        <div className="editor__group">
          <h3>In-store sale</h3>
          <div className="inline-form">
            <label htmlFor={`sale-${item.stock_id}`}>Copies</label>
            <input
              id={`sale-${item.stock_id}`}
              type="number"
              min={1}
              max={item.available}
              value={saleQty}
              onChange={(event) => setSaleQty(event.target.value)}
            />
            <button
              type="button"
              className="btn btn--small btn--primary"
              disabled={busy || Number(saleQty) < 1 || Number(saleQty) > item.available}
              onClick={() =>
                sell.mutate(
                  { id: item.stock_id, quantity: Number(saleQty), reason: reason || undefined },
                  { onSuccess: () => setNotice(`Recorded a sale of ${saleQty}.`) },
                )
              }
            >
              Record sale
            </button>
          </div>
          <p className="hint">Sells only unreserved copies. Reserved stock must be sold by completing a reservation.</p>

          <div className="field">
            <label htmlFor={`reason-${item.stock_id}`}>Note (optional)</label>
            <input
              id={`reason-${item.stock_id}`}
              value={reason}
              maxLength={500}
              onChange={(event) => setReason(event.target.value)}
              placeholder="Delivery, recount, damaged…"
            />
          </div>
        </div>
      </div>

      <div className="editor__footer">
        <div aria-live="polite" className="small">
          {failure ? (
            <span className="tone--danger">{errorText(failure)}</span>
          ) : notice ? (
            <span className="tone--available">{notice}</span>
          ) : null}
        </div>
        <button type="button" className="btn btn--ghost btn--small" onClick={onClose}>
          Done
        </button>
      </div>
    </div>
  );
}
