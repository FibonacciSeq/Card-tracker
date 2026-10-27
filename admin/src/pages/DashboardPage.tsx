import { Link } from "react-router-dom";
import { useDashboard } from "../api/queries";

export function DashboardPage() {
  const { data, isPending, error, refetch, isFetching } = useDashboard();

  return (
    <div className="page">
      <header className="page__header">
        <div>
          <h1>Dashboard</h1>
          <p className="muted">Everything that needs attention today.</p>
        </div>
        <button type="button" className="btn btn--ghost" onClick={() => void refetch()} disabled={isFetching}>
          {isFetching ? "Refreshing…" : "Refresh"}
        </button>
      </header>

      {error ? (
        <p className="alert alert--error" role="alert">
          {error.message}
        </p>
      ) : null}

      {isPending ? (
        <p className="muted">Loading dashboard…</p>
      ) : data ? (
        <>
          <section className="stat-grid" aria-label="Shop totals">
            <Stat
              label="Waiting for you"
              value={data.pending_reservations}
              hint="New reservation requests"
              to="/reservations?status=REQUESTED"
              tone={data.pending_reservations > 0 ? "attention" : undefined}
            />
            <Stat
              label="Active holds"
              value={data.active_reservations}
              hint="Requested, confirmed, or ready"
              to="/reservations"
            />
            <Stat
              label="Special orders"
              value={data.open_requests}
              hint="Requested, quoted, or accepted"
              to="/requests"
              tone={data.open_requests > 0 ? "attention" : undefined}
            />
            <Stat
              label="Sold today"
              value={`${data.today_sales_minor}`}
              hint="Copies sold through the app"
            />
            <Stat
              label="Low stock"
              value={data.low_stock}
              hint="Online cards with 2 or fewer available"
              to="/stock"
              tone={data.low_stock > 0 ? "attention" : undefined}
            />
            <Stat
              label="Stale stock"
              value={data.stale_stock}
              hint="Online cards not updated in 7 days"
              to="/stock"
              tone={data.stale_stock > 0 ? "attention" : undefined}
            />
            <Stat
              label="Shop currency"
              value={data.currency}
              hint="Prices are stored in this currency"
            />
          </section>

          <section className="card" aria-labelledby="next-title">
            <h2 id="next-title">What to do next</h2>
            {data.pending_reservations > 0 ? (
              <p>
                <Link to="/reservations?status=REQUESTED">
                  {data.pending_reservations} reservation{data.pending_reservations === 1 ? "" : "s"}
                </Link>{" "}
                still waiting for a decision. Customers are holding stock until you respond.
              </p>
            ) : (
              <p className="muted">No new reservation requests. Keep stock counts accurate so holds stay trustworthy.</p>
            )}
            {data.open_requests > 0 ? (
              <p>
                <Link to="/requests">
                  {data.open_requests} special order{data.open_requests === 1 ? "" : "s"}
                </Link>{" "}
                waiting for a quote or a conversion.
              </p>
            ) : null}
            {data.stale_stock > 0 ? (
              <p>
                {data.stale_stock} online card{data.stale_stock === 1 ? " has" : "s have"} not been touched in a week.
                Confirm the counts before the next customer trusts them.
              </p>
            ) : null}
          </section>
        </>
      ) : null}
    </div>
  );
}

type StatProps = {
  label: string;
  value: string | number;
  hint: string;
  to?: string;
  tone?: "attention";
};

function Stat({ label, value, hint, to, tone }: StatProps) {
  const body = (
    <>
      <span className="stat__label">{label}</span>
      <span className="stat__value">{value}</span>
      <span className="stat__hint">{hint}</span>
    </>
  );

  return to ? (
    <Link to={to} className={`stat${tone ? ` stat--${tone}` : ""}`}>
      {body}
    </Link>
  ) : (
    <div className={`stat${tone ? ` stat--${tone}` : ""}`}>{body}</div>
  );
}
