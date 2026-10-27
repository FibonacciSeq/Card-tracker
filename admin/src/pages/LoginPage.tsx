import { useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { ApiError } from "../api/client";
import { useAuth } from "../auth/context";

const LAST_SLUG_KEY = "cardtracker.admin.last-slug";

export function LoginPage() {
  const { session, signIn } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [slug, setSlug] = useState(() => window.localStorage.getItem(LAST_SLUG_KEY) ?? "");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  if (session) {
    return <Navigate to="/" replace />;
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setPending(true);
    try {
      await signIn(slug, email, password);
      window.localStorage.setItem(LAST_SLUG_KEY, slug.trim());
      const from = (location.state as { from?: string } | null)?.from;
      navigate(from && from !== "/login" ? from : "/", { replace: true });
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not reach the shop server. Check your connection.");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="login">
      <section className="login__panel" aria-labelledby="login-title">
        <div className="brand brand--large">
          <span className="brand__mark" aria-hidden="true">
            CT
          </span>
          <span className="brand__text">
            <strong>Card Tracker</strong>
            <small>Shop admin</small>
          </span>
        </div>

        <h1 id="login-title">Sign in to your shop</h1>
        <p className="muted">
          Manage live stock, reservations, and shop settings. Customers reserve through the mobile app.
        </p>

        <form className="form" onSubmit={handleSubmit} noValidate>
          <div className="field">
            <label htmlFor="slug">Shop address</label>
            <input
              id="slug"
              name="slug"
              data-testid="login-slug"
              value={slug}
              onChange={(event) => setSlug(event.target.value)}
              placeholder="bolt-shop"
              autoComplete="organization"
              autoCapitalize="none"
              spellCheck={false}
              required
            />
            <small className="hint">The short name in your shop link, e.g. bolt-shop.</small>
          </div>

          <div className="field">
            <label htmlFor="email">Email</label>
            <input
              id="email"
              name="email"
              type="email"
              data-testid="login-email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              autoComplete="username"
              required
            />
          </div>

          <div className="field">
            <label htmlFor="password">Password</label>
            <input
              id="password"
              name="password"
              type="password"
              data-testid="login-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="current-password"
              required
            />
          </div>

          {error ? (
            <p className="alert alert--error" role="alert" data-testid="login-error">
              {error}
            </p>
          ) : null}

          <button type="submit" className="btn btn--primary btn--block" disabled={pending} data-testid="login-submit">
            {pending ? "Signing in…" : "Sign in"}
          </button>
        </form>

        <p className="muted small">
          Staff accounts are created by the shop owner. Forgotten your password? Ask the owner to reset it.
        </p>
      </section>

      <aside className="login__aside" aria-hidden="true">
        <div className="login__aside-inner">
          <h2>Live stock, honest holds.</h2>
          <ul>
            <li>Reservations hold stock the moment a customer submits them.</li>
            <li>Cancellations and expiries release stock automatically.</li>
            <li>Completed reservations become sales with a full ledger.</li>
          </ul>
        </div>
      </aside>
    </div>
  );
}
