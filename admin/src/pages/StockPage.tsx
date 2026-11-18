import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ApiError, requestBlob } from "../api/client";
import {
  useAdjustStock,
  useArchiveAllStock,
  useConfirmStock,
  useDeleteAllArchivedStock,
  useDeleteArchivedStock,
  useImportStock,
  useRestoreStock,
  useSellStock,
  useStock,
  useUpdateStock,
} from "../api/queries";
import type { StaffStock, StockImportReportWithRates } from "../api/types";
import { StockLevels } from "../components/StockLevels";
import { formatDateTime, formatMoney } from "../lib/format";
import { useDebounced } from "../lib/useDebounced";
import { useLocale } from "../state/locale";

export function StockPage() {
  const { t } = useLocale();
  const [search, setSearch] = useState("");
  const [onlyOnline, setOnlyOnline] = useState(false);
  const [archivedView, setArchivedView] = useState(false);
  const [searchParams, setSearchParams] = useSearchParams();
  const staleOnly = !archivedView && (searchParams.get("stale") === "1" || searchParams.get("stale") === "true");
  const [expanded, setExpanded] = useState<string | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  const [archiveOpen, setArchiveOpen] = useState(false);
  const [archiveNotice, setArchiveNotice] = useState<string | null>(null);
  const [deleteArchiveOpen, setDeleteArchiveOpen] = useState(false);
  const [deleteNotice, setDeleteNotice] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const query = useDebounced(search.trim());
  const { data, isPending, error, refetch, isFetching } = useStock(query, onlyOnline, staleOnly, archivedView);
  const archive = useArchiveAllStock();
  const deleteArchive = useDeleteAllArchivedStock();

  const items = data?.items ?? [];

  function setStaleOnly(next: boolean) {
    const params = new URLSearchParams(searchParams);
    if (next) params.set("stale", "1");
    else params.delete("stale");
    setSearchParams(params, { replace: true });
  }

  function showView(archived: boolean) {
    setArchivedView(archived);
    setExpanded(null);
    setImportOpen(false);
    setArchiveOpen(false);
    setDeleteArchiveOpen(false);
    setArchiveNotice(null);
    setDeleteNotice(null);
    if (archived && staleOnly) setStaleOnly(false);
  }

  async function downloadCsv() {
    setExportError(null);
    setExporting(true);
    try {
      const suffix = archivedView ? "?archived=true" : "";
      const blob = await requestBlob(`/v1/staff/stock/export.csv${suffix}`);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = archivedView ? "stock-archived.csv" : "stock.csv";
      link.click();
      URL.revokeObjectURL(url);
    } catch (cause) {
      setExportError(cause instanceof ApiError ? t(cause.message) : t("Could not export stock."));
    } finally {
      setExporting(false);
    }
  }

  function confirmArchive() {
    archive.mutate(undefined, {
      onSuccess: (result) => {
        setArchiveOpen(false);
        setExpanded(null);
        showView(true);
        setArchiveNotice(
          result.reserved > 0
            ? `${t("Archived {count} stock items.", { count: result.archived })} ` +
                t("{count} reserved copies are still held for customers.", { count: result.reserved })
            : t("Archived {count} stock items.", { count: result.archived }),
        );
      },
    });
  }

  function confirmDeleteArchive() {
    deleteArchive.mutate(undefined, {
      onSuccess: (result) => {
        setDeleteArchiveOpen(false);
        setExpanded(null);
        setDeleteNotice(
          result.deleted === 0 && result.kept === 0
            ? t("There was no archived stock to delete.")
            : result.kept > 0
              ? `${t("Permanently deleted {count} archived items.", { count: result.deleted })} ` +
                  t("{count} items were kept because customers still have holds on them.", { count: result.kept })
              : t("Permanently deleted {count} archived items.", { count: result.deleted }),
        );
      },
    });
  }

  return (
    <div className="page">
      <header className="page__header">
        <div>
          <h1>{t("Stock")}</h1>
          <p className="muted">
            {archivedView
              ? t(
                  "Archived stock is hidden from the customer app. Restore a row, import a matching card, or delete it permanently.",
                )
              : staleOnly
                ? t(
                    "Online cards that have not been updated recently. Confirm each count is still accurate so customers can trust the shelf.",
                  )
                : t("Only online stock is visible to customers in the app.")}
          </p>
        </div>
        <button type="button" className="btn btn--ghost" onClick={() => void refetch()} disabled={isFetching}>
          {isFetching ? t("Refreshing…") : t("Refresh")}
        </button>
      </header>

      <div className="tabs" role="tablist" aria-label={t("Stock view")}>
        <button
          type="button"
          role="tab"
          aria-selected={!archivedView}
          className={`tab${!archivedView ? " tab--active" : ""}`}
          onClick={() => showView(false)}
          data-testid="stock-tab-active"
        >
          {t("Active stock")}
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={archivedView}
          className={`tab${archivedView ? " tab--active" : ""}`}
          onClick={() => showView(true)}
          data-testid="stock-tab-archived"
        >
          {t("Archived")}
        </button>
      </div>

      <div className="toolbar">
        <div className="field field--inline">
          <label htmlFor="stock-search">{t("Search cards")}</label>
          <input
            id="stock-search"
            type="search"
            placeholder={t("Card name, set, or collector number")}
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            data-testid="stock-search"
          />
        </div>
        {!archivedView ? (
          <>
            <label className="checkbox">
              <input
                type="checkbox"
                checked={onlyOnline}
                onChange={(event) => setOnlyOnline(event.target.checked)}
              />
              {t("Online only")}
            </label>
            <label className="checkbox">
              <input
                type="checkbox"
                checked={staleOnly}
                onChange={(event) => setStaleOnly(event.target.checked)}
                data-testid="stock-stale-only"
              />
              {t("Stale only")}
            </label>
          </>
        ) : null}
        <span className="muted small" aria-live="polite">
          {isPending
            ? t("Loading…")
            : archivedView
              ? t("{count} archived cards", { count: items.length })
              : staleOnly
                ? t("{count} stale cards", { count: items.length })
                : t("{count} cards", { count: items.length })}
        </span>
        <div className="toolbar__actions">
          <button type="button" className="btn btn--small" onClick={() => void downloadCsv()} disabled={exporting}>
            {exporting ? t("Exporting…") : t("Export CSV")}
          </button>
          {archivedView ? (
            <button
              type="button"
              className="btn btn--small btn--danger"
              onClick={() => {
                setDeleteNotice(null);
                deleteArchive.reset();
                setDeleteArchiveOpen(true);
              }}
              data-testid="archive-delete-all"
            >
              {t("Delete all archived")}
            </button>
          ) : null}
          {!archivedView ? (
            <>
              <button
                type="button"
                className="btn btn--small"
                onClick={() => setImportOpen((open) => !open)}
                aria-expanded={importOpen}
                data-testid="import-toggle"
              >
                {t("Import CSV")}
              </button>
              <button
                type="button"
                className="btn btn--small btn--danger"
                onClick={() => {
                  setArchiveNotice(null);
                  archive.reset();
                  setArchiveOpen(true);
                }}
                data-testid="archive-all"
              >
                {t("Archive all stock")}
              </button>
            </>
          ) : null}
        </div>
      </div>

      {exportError ? (
        <p className="alert alert--error" role="alert">
          {exportError}
        </p>
      ) : null}

      {archiveNotice ? (
        <p className="alert alert--success" role="status" data-testid="archive-notice">
          {archiveNotice}
        </p>
      ) : null}

      {deleteNotice ? (
        <p className="alert alert--success" role="status" data-testid="archive-delete-notice">
          {deleteNotice}
        </p>
      ) : null}

      {archiveOpen ? (
        <section className="card import-panel" aria-labelledby="archive-title" data-testid="archive-panel">
          <div className="import-panel__header">
            <div>
              <h2 id="archive-title">{t("Archive all stock?")}</h2>
              <p className="muted small">
                {t(
                  "This hides every active stock row for this shop from the customer app. Existing reservations stay valid. Re-importing a matching card automatically restores its row.",
                )}
              </p>
            </div>
            <button type="button" className="btn btn--ghost btn--small" onClick={() => setArchiveOpen(false)}>
              {t("Cancel")}
            </button>
          </div>
          {archive.error ? (
            <p className="alert alert--error" role="alert">
              {archive.error instanceof ApiError ? t(archive.error.message) : String(archive.error)}
            </p>
          ) : null}
          <div className="inline-form">
            <button
              type="button"
              className="btn btn--danger"
              onClick={confirmArchive}
              disabled={archive.isPending}
              data-testid="archive-confirm"
            >
              {archive.isPending ? t("Archiving…") : t("Archive all stock")}
            </button>
            <button
              type="button"
              className="btn btn--ghost"
              onClick={() => setArchiveOpen(false)}
              disabled={archive.isPending}
              data-testid="archive-cancel"
            >
              {t("Keep stock active")}
            </button>
          </div>
        </section>
      ) : null}

      {deleteArchiveOpen ? (
        <section className="card import-panel" aria-labelledby="archive-delete-title" data-testid="archive-delete-panel">
          <div className="import-panel__header">
            <div>
              <h2 id="archive-delete-title">{t("Delete the whole archive?")}</h2>
              <p className="muted small">
                {t(
                  "This permanently removes every archived stock row for this shop. Reservation history is kept, but the stock rows cannot be restored. Items with active customer holds are kept until those reservations close.",
                )}
              </p>
            </div>
            <button
              type="button"
              className="btn btn--ghost btn--small"
              onClick={() => setDeleteArchiveOpen(false)}
            >
              {t("Cancel")}
            </button>
          </div>
          {deleteArchive.error ? (
            <p className="alert alert--error" role="alert">
              {deleteArchive.error instanceof ApiError ? t(deleteArchive.error.message) : String(deleteArchive.error)}
            </p>
          ) : null}
          <div className="inline-form">
            <button
              type="button"
              className="btn btn--danger"
              onClick={confirmDeleteArchive}
              disabled={deleteArchive.isPending}
              data-testid="archive-delete-confirm"
            >
              {deleteArchive.isPending ? t("Deleting…") : t("Delete all archived")}
            </button>
            <button
              type="button"
              className="btn btn--ghost"
              onClick={() => setDeleteArchiveOpen(false)}
              disabled={deleteArchive.isPending}
              data-testid="archive-delete-cancel"
            >
              {t("Keep archived stock")}
            </button>
          </div>
        </section>
      ) : null}

      {importOpen && !archivedView ? <StockImport onClose={() => setImportOpen(false)} /> : null}

      {error ? (
        <p className="alert alert--error" role="alert">
          {t(error.message)}
        </p>
      ) : null}

      <div className="table-wrap">
        <table className="table" data-testid="stock-table">
          <caption className="sr-only">
            {archivedView
              ? t("Archived stock with on-hand, reserved, and available counts")
              : t("Stock with on-hand, reserved, and available counts")}
          </caption>
          <thead>
            <tr>
              <th scope="col">{t("Card")}</th>
              <th scope="col">{t("Availability")}</th>
              <th scope="col">{t("Price")}</th>
              <th scope="col">{archivedView ? t("Archived") : t("Updated")}</th>
              <th scope="col">
                <span className="sr-only">{t("Actions")}</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <StockRow
                key={item.stock_id}
                item={item}
                expanded={expanded === item.stock_id}
                staleView={staleOnly}
                onToggle={() => setExpanded(expanded === item.stock_id ? null : item.stock_id)}
              />
            ))}
          </tbody>
        </table>

        {!isPending && items.length === 0 ? (
          <div className="empty">
            <h2>{archivedView ? t("No archived stock") : t("No stock found")}</h2>
            <p className="muted">
              {archivedView
                ? t(
                    "Archive all stock from the active view to move it here. Importing a matching card restores it automatically.",
                  )
                : query
                  ? t('Nothing matches "{query}".', { query })
                  : t("Add cards from the catalog to start selling them.")}
            </p>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function StockRow({
  item,
  expanded,
  staleView,
  onToggle,
}: {
  item: StaffStock;
  expanded: boolean;
  staleView: boolean;
  onToggle: () => void;
}) {
  const { t } = useLocale();
  const restore = useRestoreStock();
  const remove = useDeleteArchivedStock();
  const confirm = useConfirmStock();
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const archived = item.archived_at != null;

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
              {archived ? <span className="badge badge--offline">{t("Archived")}</span> : null}
              {!archived && !item.is_online ? (
                <span className="badge badge--offline">{t("Not online")}</span>
              ) : null}
              {item.restock_waiting > 0 ? (
                <span
                  className="badge badge--requested"
                  title={t("Customers waiting for this variant to come back in stock")}
                  data-testid="restock-waiting"
                >
                  {t("{count} waiting", { count: item.restock_waiting })}
                </span>
              ) : null}
              {restore.error ? (
                <div className="tone--danger small" role="alert">
                  {restore.error instanceof ApiError ? t(restore.error.message) : String(restore.error)}
                </div>
              ) : null}
              {remove.error ? (
                <div className="tone--danger small" role="alert" data-testid="stock-delete-error">
                  {remove.error instanceof ApiError ? t(remove.error.message) : String(remove.error)}
                </div>
              ) : null}
              {confirm.error ? (
                <div className="tone--danger small" role="alert" data-testid="stock-confirm-error">
                  {confirm.error instanceof ApiError ? t(confirm.error.message) : String(confirm.error)}
                </div>
              ) : null}
            </div>
          </div>
        </td>
        <td>
          <StockLevels onHand={item.on_hand} reserved={item.reserved} available={item.available} />
        </td>
        <td className="num">{formatMoney(item.price.amount_minor, item.price.currency)}</td>
        <td className="muted small">{formatDateTime(item.archived_at ?? item.updated_at)}</td>
        <td>
          {archived ? (
            <div className="inline-form">
              {confirmingDelete ? (
                <>
                  <button
                    type="button"
                    className="btn btn--small btn--danger"
                    onClick={() => remove.mutate(item.stock_id)}
                    disabled={remove.isPending}
                    data-testid="stock-delete-confirm"
                  >
                    {remove.isPending ? t("Deleting…") : t("Really delete")}
                  </button>
                  <button
                    type="button"
                    className="btn btn--ghost btn--small"
                    onClick={() => {
                      setConfirmingDelete(false);
                      remove.reset();
                    }}
                    disabled={remove.isPending}
                    data-testid="stock-delete-cancel"
                  >
                    {t("Cancel")}
                  </button>
                </>
              ) : (
                <>
                  <button
                    type="button"
                    className="btn btn--small"
                    onClick={() => restore.mutate(item.stock_id)}
                    disabled={restore.isPending}
                    data-testid="stock-restore"
                  >
                    {restore.isPending ? t("Restoring…") : t("Restore")}
                  </button>
                  <button
                    type="button"
                    className="btn btn--small btn--danger"
                    onClick={() => {
                      remove.reset();
                      setConfirmingDelete(true);
                    }}
                    data-testid="stock-delete"
                  >
                    {t("Delete")}
                  </button>
                </>
              )}
            </div>
          ) : (
            <div className="inline-form">
              {staleView ? (
                <button
                  type="button"
                  className="btn btn--small btn--primary"
                  onClick={() => confirm.mutate(item.stock_id)}
                  disabled={confirm.isPending}
                  data-testid="stock-confirm"
                >
                  {confirm.isPending ? t("Confirming…") : t("Confirm available")}
                </button>
              ) : null}
              <button type="button" className="btn btn--small" onClick={onToggle} aria-expanded={expanded}>
                {expanded ? t("Close") : t("Manage")}
              </button>
            </div>
          )}
        </td>
      </tr>
      {expanded && !archived ? (
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
  const { t } = useLocale();
  const update = useUpdateStock();
  const adjust = useAdjustStock();
  const sell = useSellStock();
  const confirm = useConfirmStock();

  const [quantity, setQuantity] = useState(String(item.on_hand));
  const [price, setPrice] = useState((item.price.amount_minor / 100).toFixed(2));
  const [delta, setDelta] = useState("1");
  const [reason, setReason] = useState("");
  const [saleQty, setSaleQty] = useState("1");
  const [notice, setNotice] = useState<string | null>(null);

  const busy = update.isPending || adjust.isPending || sell.isPending || confirm.isPending;
  const failure = update.error ?? adjust.error ?? sell.error ?? confirm.error;

  function errorText(cause: unknown): string {
    return cause instanceof ApiError ? t(cause.message) : String(cause);
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
          <h3>{t("Counts")}</h3>
          <div className="inline-form">
            <label htmlFor={`qty-${item.stock_id}`}>{t("On hand")}</label>
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
              onClick={() => saveStock({ quantity: Number(quantity) }, t("On-hand count saved."))}
            >
              {t("Save")}
            </button>
          </div>
          <p className="hint">
            {t(
              "Cannot drop below the {count} reserved copies. Use an adjustment for deliveries or shelf recounts so the ledger stays correct.",
              { count: item.reserved },
            )}
          </p>

          <div className="inline-form">
            <button
              type="button"
              className="btn btn--small btn--primary"
              disabled={busy}
              onClick={() =>
                confirm.mutate(item.stock_id, {
                  onSuccess: () => setNotice(t("Counts confirmed today — this row is no longer stale.")),
                })
              }
              data-testid="stock-confirm-editor"
            >
              {confirm.isPending ? t("Confirming…") : t("Confirm still available")}
            </button>
          </div>
          <p className="hint">{t("Marks the row as checked today without changing the quantity or ledger.")}</p>

          <div className="inline-form">
            <label htmlFor={`delta-${item.stock_id}`}>{t("Adjust by")}</label>
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
                  {
                    onSuccess: () =>
                      setNotice(t("Added {count} to stock.", { count: Math.abs(Number(delta)) })),
                  },
                )
              }
            >
              {t("Add")}
            </button>
            <button
              type="button"
              className="btn btn--small"
              disabled={busy || !Number(delta)}
              onClick={() =>
                adjust.mutate(
                  { id: item.stock_id, delta: -Math.abs(Number(delta)), reason: reason || undefined },
                  {
                    onSuccess: () =>
                      setNotice(t("Removed {count} from stock.", { count: Math.abs(Number(delta)) })),
                  },
                )
              }
            >
              {t("Remove")}
            </button>
          </div>
        </div>

        <div className="editor__group">
          <h3>{t("Price & visibility")}</h3>
          <div className="inline-form">
            <label htmlFor={`price-${item.stock_id}`}>
              {t("Price ({currency})", { currency: item.price.currency })}
            </label>
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
              onClick={() => saveStock({ price_minor: priceMinor }, t("Price saved."))}
            >
              {t("Save")}
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
                  event.target.checked
                    ? t("Card is now visible to customers.")
                    : t("Card hidden from the app."),
                )
              }
            />
            {t("Visible in the customer app")}
          </label>
        </div>

        <div className="editor__group">
          <h3>{t("In-store sale")}</h3>
          <div className="inline-form">
            <label htmlFor={`sale-${item.stock_id}`}>{t("Copies")}</label>
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
                  { onSuccess: () => setNotice(t("Recorded a sale of {count}.", { count: saleQty })) },
                )
              }
            >
              {t("Record sale")}
            </button>
          </div>
          <p className="hint">
            {t("Sells only unreserved copies. Reserved stock must be sold by completing a reservation.")}
          </p>

          <div className="field">
            <label htmlFor={`reason-${item.stock_id}`}>{t("Note (optional)")}</label>
            <input
              id={`reason-${item.stock_id}`}
              value={reason}
              maxLength={500}
              onChange={(event) => setReason(event.target.value)}
              placeholder={t("Delivery, recount, damaged…")}
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
          {t("Done")}
        </button>
      </div>
    </div>
  );
}

function StockImport({ onClose }: { onClose: () => void }) {
  const { t } = useLocale();
  const [file, setFile] = useState<File | null>(null);
  const [checked, setChecked] = useState(false);
  const [report, setReport] = useState<StockImportReportWithRates | null>(null);
  const mutation = useImportStock();

  function invalidateCheck() {
    setChecked(false);
    setReport(null);
  }

  function run(dryRun: boolean) {
    if (!file) return;
    mutation.mutate(
      { file, dryRun },
      {
        onSuccess: (result) => {
          setReport(result);
          if (dryRun) setChecked(true);
        },
      },
    );
  }

  return (
    <section className="card import-panel" aria-labelledby="import-title" data-testid="import-panel">
      <div className="import-panel__header">
        <div>
          <h2 id="import-title">{t("Import stock from CSV")}</h2>
          <p className="muted small">
            {t("Upload a stock CSV or ManaBox collection export. Check the file before applying any changes.")}
          </p>
        </div>
        <button type="button" className="btn btn--ghost btn--small" onClick={onClose}>
          {t("Close")}
        </button>
      </div>

      <div className="inline-form">
        <label htmlFor="import-file">{t("CSV file")}</label>
        <input
          id="import-file"
          type="file"
          accept=".csv,text/csv"
          data-testid="import-file"
          onChange={(event) => {
            setFile(event.target.files?.[0] ?? null);
            invalidateCheck();
          }}
        />
        <button
          type="button"
          className="btn btn--small"
          disabled={!file || mutation.isPending}
          onClick={() => run(true)}
          data-testid="import-check"
        >
          {mutation.isPending && !checked ? t("Checking…") : t("Check file")}
        </button>
        <button
          type="button"
          className="btn btn--small btn--primary"
          disabled={!file || !checked || mutation.isPending}
          onClick={() => run(false)}
          data-testid="import-apply"
        >
          {t("Apply import")}
        </button>
      </div>

      {mutation.error ? (
        <p className="alert alert--error" role="alert">
          {mutation.error instanceof ApiError ? t(mutation.error.message) : String(mutation.error)}
        </p>
      ) : null}

      {report ? (
        <div aria-live="polite" data-testid="import-report">
          <p>
            <strong>{report.dry_run ? t("Check only — nothing changed.") : t("Import applied.")}</strong>{" "}
            {t("{rows} rows: {created} new, {updated} updated, {unchanged} unchanged, {errors} problems.", {
              rows: report.rows,
              created: report.created,
              updated: report.updated,
              unchanged: report.unchanged,
              errors: report.errors.length,
            })}
          </p>
          {report.exchange_rates.length > 0 ? (
            <p className="muted small">
              {t("Daily rate used:")}{" "}
              {report.exchange_rates
                .map((rate) =>
                  t("1 {source} = {rate} {target} ({date})", {
                    source: rate.source_currency,
                    rate: rate.rate,
                    target: rate.target_currency,
                    date: rate.rate_date,
                  }),
                )
                .join("; ")}
            </p>
          ) : null}
          {report.errors.length > 0 ? (
            <table className="table table--tight">
              <caption className="sr-only">{t("Rows that will be skipped")}</caption>
              <thead>
                <tr>
                  <th scope="col">{t("Row")}</th>
                  <th scope="col">{t("Column")}</th>
                  <th scope="col">{t("Problem")}</th>
                </tr>
              </thead>
              <tbody>
                {report.errors.map((issue, index) => (
                  <tr key={`${issue.row}-${issue.field ?? "row"}-${index}`}>
                    <td className="num">{issue.row}</td>
                    <td>{issue.field ?? "—"}</td>
                    <td>{t(issue.message)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
