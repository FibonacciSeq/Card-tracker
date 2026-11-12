import { useEffect, useRef, useState } from "react";
import { QRCodeCanvas } from "qrcode.react";
import { ApiError } from "../api/client";
import { useRefreshScryfallPrices, useSettings, useUpdateSettings } from "../api/queries";
import type { SettingsUpdate, StaffShop } from "../api/types";

function asText(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null ? (value as Record<string, unknown>) : {};
}

type FormState = {
  brandName: string;
  logoUrl: string;
  primary: string;
  accent: string;
  holdHours: string;
  archiveRetentionDays: string;
  paymentInstructions: string;
  directoryOptIn: boolean;
  contactEmail: string;
  contactPhone: string;
  contactAddress: string;
  scryfallPricingEnabled: boolean;
  scryfallMinimumPrice: string;
  scryfallMarkupPercent: string;
  scryfallRoundingIncrement: string;
}

function toForm(shop: StaffShop): FormState {
  const colors = asRecord(shop.colors);
  const contact = asRecord(shop.contact);
  return {
    brandName: shop.brand_name ?? shop.name,
    logoUrl: shop.logo_url ?? "",
    primary: asText(colors.primary, "#2f6fed"),
    accent: asText(colors.accent, "#f0a202"),
    holdHours: String(shop.hold_hours),
    archiveRetentionDays: String(shop.archive_retention_days),
    paymentInstructions: shop.payment_instructions,
    directoryOptIn: shop.directory_opt_in,
    contactEmail: asText(contact.email),
    contactPhone: asText(contact.phone),
    contactAddress: asText(contact.address),
    scryfallPricingEnabled: shop.scryfall_pricing_enabled,
    scryfallMinimumPrice: (shop.scryfall_min_price_minor / 100).toFixed(2),
    scryfallMarkupPercent: String(shop.scryfall_markup_percent),
    scryfallRoundingIncrement: String(shop.scryfall_rounding_increment),
  };
}

export function SettingsPage() {
  const { data: shop, isPending, error } = useSettings();

  if (error) {
    return (
      <div className="page">
        <h1>Settings</h1>
        <p className="alert alert--error" role="alert">
          {error.message}
        </p>
      </div>
    );
  }

  if (isPending || !shop) {
    return (
      <div className="page">
        <h1>Settings</h1>
        <p className="muted">Loading shop settings…</p>
      </div>
    );
  }

  // Keyed by slug so a refetch does not overwrite edits in progress.
  return <SettingsForm key={shop.slug} shop={shop} />;
}

function ShopQrPanel({ slug }: { slug: string }) {
  const publicBase = (import.meta.env.VITE_PUBLIC_APP_BASE_URL ?? import.meta.env.VITE_APP_BASE_URL ?? "https://app.cardtracker.local").replace(/\/+$/, "");
  const publicLink = `${publicBase}/shop/${encodeURIComponent(slug)}`;
  const fallbackLink = `cardtracker://shop/${encodeURIComponent(slug)}`;
  const appStoreUrl = import.meta.env.VITE_APP_STORE_URL || "";
  const playStoreUrl = import.meta.env.VITE_PLAY_STORE_URL || "";
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), 2500);
    return () => clearTimeout(timer);
  }, [copied]);

  async function copyLink() {
    try {
      await navigator.clipboard.writeText(publicLink);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  function downloadPng() {
    const canvas = canvasRef.current;
    if (!canvas) return;
    canvas.toBlob((blob) => {
      if (!blob) return;
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `${slug}-cardtracker-qr.png`;
      anchor.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    }, "image/png");
  }

  return (
    <section className="card qr-panel" data-testid="shop-qr-panel" aria-labelledby="shop-qr-title">
      <div className="qr-panel__code">
        <QRCodeCanvas
          ref={canvasRef}
          value={publicLink}
          size={168}
          marginSize={4}
          level="M"
          bgColor="#ffffff"
          fgColor="#15181d"
          title={`QR code that opens the ${slug} storefront`}
        />
      </div>
      <div className="qr-panel__body">
        <h2 id="shop-qr-title">Shop QR code</h2>
        <p className="muted">
          Print this and put it on the counter. Customers scan it in the Card Tracker app
          to open your storefront and see live stock. The QR points at the public HTTPS app link,
          while the fallback custom-scheme URL remains available for direct app installs.
        </p>
        <div className="mono small">{publicLink}</div>
        <div className="mono small muted">App fallback: {fallbackLink}</div>
        {(appStoreUrl || playStoreUrl) && (
          <div className="qr-panel__actions">
            {appStoreUrl ? (
              <a className="btn btn--small" href={appStoreUrl} target="_blank" rel="noreferrer">
                App Store
              </a>
            ) : null}
            {playStoreUrl ? (
              <a className="btn btn--small" href={playStoreUrl} target="_blank" rel="noreferrer">
                Google Play
              </a>
            ) : null}
          </div>
        )}
        <div className="qr-panel__actions">
          <button type="button" className="btn btn--small" onClick={() => void copyLink()}>
            {copied ? "Copied" : "Copy link"}
          </button>
          <button type="button" className="btn btn--small" onClick={downloadPng}>
            Download PNG
          </button>
          <span className="small tone--available" aria-live="polite">
            {copied ? "Link copied." : null}
          </span>
        </div>
      </div>
    </section>
  );
}

function SettingsForm({ shop }: { shop: StaffShop }) {
  const update = useUpdateSettings();
  const refreshScryfall = useRefreshScryfallPrices();
  const [form, setForm] = useState<FormState>(() => toForm(shop));
  const [saved, setSaved] = useState(false);

  const holdHours = Number(form.holdHours);
  const holdValid = Number.isInteger(holdHours) && holdHours >= 1 && holdHours <= 720;
  const retentionDays = Number(form.archiveRetentionDays);
  const retentionValid =
    form.archiveRetentionDays.trim() !== "" &&
    Number.isInteger(retentionDays) &&
    retentionDays >= 0 &&
    retentionDays <= 3650;
  const minimumPriceMinor = parseMinorAmount(form.scryfallMinimumPrice);
  const markupPercent = Number(form.scryfallMarkupPercent);
  const roundingIncrement = Number(form.scryfallRoundingIncrement);
  const pricingValid =
    minimumPriceMinor !== null &&
    form.scryfallMarkupPercent.trim() !== "" &&
    Number.isInteger(markupPercent) &&
    markupPercent >= 0 &&
    markupPercent <= 10_000 &&
    Number.isInteger(roundingIncrement) &&
    roundingIncrement >= 1 &&
    roundingIncrement <= 21_474_836;

  function patch(next: Partial<FormState>) {
    setSaved(false);
    setForm((current) => ({ ...current, ...next }));
  }

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const body: SettingsUpdate = {
      brand_name: form.brandName.trim() || null,
      logo_url: form.logoUrl.trim() || null,
      colors: { ...asRecord(shop.colors), primary: form.primary, accent: form.accent },
      contact: {
        ...asRecord(shop.contact),
        email: form.contactEmail.trim(),
        phone: form.contactPhone.trim(),
        address: form.contactAddress.trim(),
      },
      hold_hours: holdHours,
      archive_retention_days: Number.isInteger(retentionDays) ? retentionDays : 0,
      payment_instructions: form.paymentInstructions,
      directory_opt_in: form.directoryOptIn,
      scryfall_pricing_enabled: form.scryfallPricingEnabled,
      scryfall_min_price_minor: minimumPriceMinor ?? 0,
      scryfall_markup_percent: Number.isInteger(markupPercent) ? markupPercent : 0,
      scryfall_rounding_increment: Number.isInteger(roundingIncrement) ? roundingIncrement : 5,
    };
    update.mutate(body, { onSuccess: () => setSaved(true) });
  }

  const failure = update.error ?? refreshScryfall.error;

  return (
    <div className="page">
      <header className="page__header">
        <div>
          <h1>Settings</h1>
          <p className="muted">Branding and policies customers see in the app.</p>
        </div>
      </header>

      <div className="facts">
        <div>
          <span className="muted small">Shop address</span>
          <div className="mono">{shop.slug}</div>
        </div>
        <div>
          <span className="muted small">Currency</span>
          <div>{shop.currency}</div>
        </div>
        <div>
          <span className="muted small">Timezone</span>
          <div>{shop.timezone}</div>
        </div>
      </div>

      <ShopQrPanel slug={shop.slug} />

      <form className="form form--wide" onSubmit={handleSubmit} data-testid="settings-form">
        <fieldset>
          <legend>Branding</legend>
          <div className="field">
            <label htmlFor="brand-name">Display name</label>
            <input
              id="brand-name"
              value={form.brandName}
              onChange={(event) => patch({ brandName: event.target.value })}
              maxLength={200}
            />
          </div>
          <div className="field">
            <label htmlFor="logo-url">Logo URL</label>
            <input
              id="logo-url"
              type="url"
              value={form.logoUrl}
              onChange={(event) => patch({ logoUrl: event.target.value })}
              placeholder="https://…"
            />
            <small className="hint">Square images work best. Leave empty to show the shop name only.</small>
          </div>
          <div className="field-row">
            <div className="field">
              <label htmlFor="color-primary">Primary colour</label>
              <input
                id="color-primary"
                type="color"
                value={form.primary}
                onChange={(event) => patch({ primary: event.target.value })}
              />
            </div>
            <div className="field">
              <label htmlFor="color-accent">Accent colour</label>
              <input
                id="color-accent"
                type="color"
                value={form.accent}
                onChange={(event) => patch({ accent: event.target.value })}
              />
            </div>
          </div>
        </fieldset>

        <fieldset>
          <legend>Reservations</legend>
          <div className="field">
            <label htmlFor="hold-hours">Hold duration (hours)</label>
            <input
              id="hold-hours"
              type="number"
              min={1}
              max={720}
              value={form.holdHours}
              onChange={(event) => patch({ holdHours: event.target.value })}
              aria-invalid={!holdValid}
            />
            <small className="hint">
              Stock is released automatically when a hold is not collected in time. Default is 24 hours.
            </small>
          </div>
        </fieldset>

        <fieldset>
          <legend>Archived stock</legend>
          <div className="field">
            <label htmlFor="archive-retention-days">Delete archived cards after (days)</label>
            <input
              id="archive-retention-days"
              type="number"
              min={0}
              max={3650}
              value={form.archiveRetentionDays}
              onChange={(event) => patch({ archiveRetentionDays: event.target.value })}
              aria-invalid={!retentionValid}
            />
            <small className="hint">
              Archived cards older than this are permanently deleted automatically. Use 0 to keep archived stock
              forever. Rows with active customer holds are kept until those reservations close.
            </small>
          </div>
        </fieldset>

        <fieldset>
          <legend>Stock pricing</legend>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={form.scryfallPricingEnabled}
              onChange={(event) => patch({ scryfallPricingEnabled: event.target.checked })}
            />
            Automatically price stock using Scryfall market prices
          </label>
          <div className="field-row">
            <div className="field">
              <label htmlFor="scryfall-minimum-price">Minimum price ({shop.currency})</label>
              <input
                id="scryfall-minimum-price"
                type="number"
                min="0"
                step="0.01"
                value={form.scryfallMinimumPrice}
                onChange={(event) => patch({ scryfallMinimumPrice: event.target.value })}
                aria-invalid={!pricingValid}
              />
            </div>
            <div className="field">
              <label htmlFor="scryfall-markup">Markup at/above minimum (%)</label>
              <input
                id="scryfall-markup"
                type="number"
                min="0"
                max="10000"
                step="1"
                value={form.scryfallMarkupPercent}
                onChange={(event) => patch({ scryfallMarkupPercent: event.target.value })}
                aria-invalid={!pricingValid}
              />
            </div>
            <div className="field">
              <label htmlFor="scryfall-rounding-increment">Round up to next multiple of ({shop.currency})</label>
              <input
                id="scryfall-rounding-increment"
                type="number"
                min="1"
                max="21474836"
                step="1"
                value={form.scryfallRoundingIncrement}
                onChange={(event) => patch({ scryfallRoundingIncrement: event.target.value })}
                aria-invalid={!pricingValid}
              />
            </div>
          </div>
          <p className="hint">
            Below the minimum, the sale price is set to the minimum. At or above it, the configured percentage is added,
            then the result rounds strictly up to the next multiple of the configured whole-currency increment. For
            example, an increment of 5 rounds 121 up to 125 and 125 up to 130. Scryfall prices refresh nightly at 02:00
            UTC and use the finish-specific market price. Cards without a reported market price are skipped during
            imports; existing stock keeps its last price.
          </p>
          <div className="field">
            <button
              type="button"
              className="btn"
              data-testid="scryfall-refresh"
              onClick={() => refreshScryfall.mutate()}
              disabled={
                !form.scryfallPricingEnabled || !pricingValid || refreshScryfall.isPending || update.isPending
              }
            >
              {refreshScryfall.isPending ? "Fetching prices…" : "Update prices from Scryfall now"}
            </button>
            <small className="hint">
              Fetches the current Scryfall market prices for the cards in stock and reprices them immediately, using the
              saved rules above. The nightly refresh at 02:00 UTC keeps running either way.
            </small>
            <span aria-live="polite" className="small tone--available" data-testid="scryfall-refresh-result">
              {refreshScryfall.data
                ? `Fetched current Scryfall prices for ${refreshScryfall.data.cards_refreshed} cards (${refreshScryfall.data.cards_unavailable} unavailable). Updated ${refreshScryfall.data.repriced_stock} stock prices; ${refreshScryfall.data.stock_without_scryfall_prices} rows had no market price and were left unchanged.`
                : null}
            </span>
          </div>
        </fieldset>

        <fieldset>
          <legend>Storefront</legend>
          <div className="field">
            <label htmlFor="payment-instructions">Payment instructions</label>
            <textarea
              id="payment-instructions"
              rows={4}
              maxLength={4000}
              value={form.paymentInstructions}
              onChange={(event) => patch({ paymentInstructions: event.target.value })}
              placeholder="Pay in store by card or cash when you collect."
            />
          </div>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={form.directoryOptIn}
              onChange={(event) => patch({ directoryOptIn: event.target.checked })}
            />
            Show this shop in the public shop directory
          </label>
        </fieldset>

        <fieldset>
          <legend>Contact</legend>
          <div className="field">
            <label htmlFor="contact-email">Email</label>
            <input
              id="contact-email"
              type="email"
              value={form.contactEmail}
              onChange={(event) => patch({ contactEmail: event.target.value })}
            />
          </div>
          <div className="field">
            <label htmlFor="contact-phone">Phone</label>
            <input
              id="contact-phone"
              value={form.contactPhone}
              onChange={(event) => patch({ contactPhone: event.target.value })}
            />
          </div>
          <div className="field">
            <label htmlFor="contact-address">Address</label>
            <input
              id="contact-address"
              value={form.contactAddress}
              onChange={(event) => patch({ contactAddress: event.target.value })}
            />
          </div>
          <p className="hint">Opening hours editing arrives with the storefront profile work.</p>
        </fieldset>

        {failure ? (
          <p className="alert alert--error" role="alert">
            {failure instanceof ApiError && failure.status === 403
              ? "Only the shop owner can change settings."
              : failure.message}
          </p>
        ) : null}

        <div className="form__footer">
          <button
            type="submit"
            className="btn btn--primary"
            disabled={update.isPending || !holdValid || !retentionValid || !pricingValid}
          >
            {update.isPending ? "Saving…" : "Save settings"}
          </button>
          <span aria-live="polite" className="small tone--available">
            {saved
              ? update.data?.repriced_stock !== null && update.data?.repriced_stock !== undefined
                ? `Settings saved. Updated ${update.data.repriced_stock} stock prices; ${update.data.stock_without_scryfall_prices ?? 0} rows had no Scryfall price and were left unchanged.`
                : "Settings saved."
              : null}
          </span>
        </div>
      </form>
    </div>
  );
}

function parseMinorAmount(value: string): number | null {
  if (!value.trim()) return null;
  const amount = Number(value);
  const minor = Math.round(amount * 100);
  return Number.isFinite(amount) && amount >= 0 && Number.isSafeInteger(minor) && minor <= 2_147_483_647
    ? minor
    : null;
}
