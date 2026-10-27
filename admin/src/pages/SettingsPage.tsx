import { useState } from "react";
import { ApiError } from "../api/client";
import { useSettings, useUpdateSettings } from "../api/queries";
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
  paymentInstructions: string;
  directoryOptIn: boolean;
  notificationEmail: string;
  contactEmail: string;
  contactPhone: string;
  contactAddress: string;
};

function toForm(shop: StaffShop): FormState {
  const colors = asRecord(shop.colors);
  const contact = asRecord(shop.contact);
  return {
    brandName: shop.brand_name ?? shop.name,
    logoUrl: shop.logo_url ?? "",
    primary: asText(colors.primary, "#2f6fed"),
    accent: asText(colors.accent, "#f0a202"),
    holdHours: String(shop.hold_hours),
    paymentInstructions: shop.payment_instructions,
    directoryOptIn: shop.directory_opt_in,
    notificationEmail: shop.notification_email ?? "",
    contactEmail: asText(contact.email),
    contactPhone: asText(contact.phone),
    contactAddress: asText(contact.address),
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

function SettingsForm({ shop }: { shop: StaffShop }) {
  const update = useUpdateSettings();
  const [form, setForm] = useState<FormState>(() => toForm(shop));
  const [saved, setSaved] = useState(false);

  const holdHours = Number(form.holdHours);
  const holdValid = Number.isInteger(holdHours) && holdHours >= 1 && holdHours <= 720;

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
      payment_instructions: form.paymentInstructions,
      directory_opt_in: form.directoryOptIn,
      notification_email: form.notificationEmail.trim() || null,
    };
    update.mutate(body, { onSuccess: () => setSaved(true) });
  }

  const failure = update.error;

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
          <div className="field">
            <label htmlFor="notification-email">Reservation alert email</label>
            <input
              id="notification-email"
              type="email"
              value={form.notificationEmail}
              onChange={(event) => patch({ notificationEmail: event.target.value })}
              placeholder="orders@yourshop.example"
            />
            <small className="hint">New reservations are queued for this address once notifications are enabled.</small>
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
          <button type="submit" className="btn btn--primary" disabled={update.isPending || !holdValid}>
            {update.isPending ? "Saving…" : "Save settings"}
          </button>
          <span aria-live="polite" className="small tone--available">
            {saved ? "Settings saved." : null}
          </span>
        </div>
      </form>
    </div>
  );
}
