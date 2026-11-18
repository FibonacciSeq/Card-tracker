import { Link } from "react-router-dom";
import { useDashboard } from "../api/queries";
import { useLocale } from "../state/locale";

export function DashboardPage() {
  const { t } = useLocale();
  const { data, isPending, error, refetch, isFetching } = useDashboard();

  return (
    <div className="page">
      <header className="page__header">
        <div>
          <h1>{t("Dashboard")}</h1>
          <p className="muted">{t("Everything that needs attention today.")}</p>
        </div>
        <button type="button" className="btn btn--ghost" onClick={() => void refetch()} disabled={isFetching}>
          {isFetching ? t("Refreshing…") : t("Refresh")}
        </button>
      </header>

      {error ? (
        <p className="alert alert--error" role="alert">
          {t(error.message)}
        </p>
      ) : null}

      {isPending ? (
        <p className="muted">{t("Loading dashboard…")}</p>
      ) : data ? (
        <>
          <section className="stat-grid" aria-label={t("Shop totals")}>
            <Stat
              label={t("Waiting for you")}
              value={data.pending_reservations}
              hint={t("New reservation requests")}
              to="/reservations?status=REQUESTED"
              tone={data.pending_reservations > 0 ? "attention" : undefined}
            />
            <Stat
              label={t("Active holds")}
              value={data.active_reservations}
              hint={t("Requested, confirmed, or ready")}
              to="/reservations"
            />
            <Stat
              label={t("Special orders")}
              value={data.open_requests}
              hint={t("Requested, quoted, or accepted")}
              to="/requests"
              tone={data.open_requests > 0 ? "attention" : undefined}
            />
            <Stat
              label={t("Sold today")}
              value={`${data.today_sales_minor}`}
              hint={t("Copies sold through the app")}
            />
            <Stat
              label={t("Low stock")}
              value={data.low_stock}
              hint={t("Online cards with 2 or fewer available")}
              to="/stock"
              tone={data.low_stock > 0 ? "attention" : undefined}
            />
            <Stat
              label={t("Stale stock")}
              value={data.stale_stock}
              hint={t("Online cards not updated in 7 days")}
              to="/stock?stale=1"
              tone={data.stale_stock > 0 ? "attention" : undefined}
            />
            <Stat
              label={t("Shop currency")}
              value={data.currency}
              hint={t("Prices are stored in this currency")}
            />
          </section>

          <section className="card" aria-labelledby="next-title">
            <h2 id="next-title">{t("What to do next")}</h2>
            {data.pending_reservations > 0 ? (
              <p>
                <Link to="/reservations?status=REQUESTED">
                  {data.pending_reservations === 1
                    ? t("{count} reservation", { count: data.pending_reservations })
                    : t("{count} reservations", { count: data.pending_reservations })}
                </Link>{" "}
                {t("still waiting for a decision. Customers are holding stock until you respond.")}
              </p>
            ) : (
              <p className="muted">
                {t("No new reservation requests. Keep stock counts accurate so holds stay trustworthy.")}
              </p>
            )}
            {data.open_requests > 0 ? (
              <p>
                <Link to="/requests">
                  {data.open_requests === 1
                    ? t("{count} special order", { count: data.open_requests })
                    : t("{count} special orders", { count: data.open_requests })}
                </Link>{" "}
                {t("waiting for a quote or a conversion.")}
              </p>
            ) : null}
            {data.stale_stock > 0 ? (
              <p>
                <Link to="/stock?stale=1">
                  {data.stale_stock === 1
                    ? t("{count} online card", { count: data.stale_stock })
                    : t("{count} online cards", { count: data.stale_stock })}
                </Link>{" "}
                {data.stale_stock === 1 ? t("has") : t("have")}{" "}
                {t("not been touched in a week. Confirm the counts before the next customer trusts them.")}
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
