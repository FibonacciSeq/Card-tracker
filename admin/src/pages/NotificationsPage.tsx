import { Link } from "react-router-dom";
import { ApiError } from "../api/client";
import {
  useMarkAllNotificationsRead,
  useMarkNotificationRead,
  useStaffNotifications,
} from "../api/queries";
import { formatDateTime } from "../lib/format";

export function NotificationsPage() {
  const notifications = useStaffNotifications();
  const markRead = useMarkNotificationRead();
  const markAll = useMarkAllNotificationsRead();

  const items = notifications.data?.pages.flatMap((page) => page.items) ?? [];
  const unreadCount = notifications.data?.pages[0]?.unread_count ?? 0;
  const error = notifications.error ?? markRead.error ?? markAll.error;

  return (
    <div className="page">
      <header className="page__header">
        <div>
          <h1>Notifications</h1>
          <p className="muted">Changes that need your attention.</p>
        </div>
        <div className="page__actions">
          <button
            type="button"
            className="btn btn--ghost"
            onClick={() => void notifications.refetch()}
            disabled={notifications.isFetching}
          >
            {notifications.isFetching ? "Refreshing…" : "Refresh"}
          </button>
          <button
            type="button"
            className="btn btn--ghost"
            onClick={() => markAll.mutate()}
            disabled={unreadCount === 0 || markAll.isPending}
          >
            {markAll.isPending ? "Marking…" : "Mark all read"}
          </button>
        </div>
      </header>

      {error ? (
        <p className="alert alert--error" role="alert">
          {error instanceof ApiError ? error.message : "Could not load notifications."}
        </p>
      ) : null}

      {notifications.isPending ? <p className="muted">Loading…</p> : null}

      {notifications.data && items.length === 0 ? (
        <div className="card">
          <p className="muted">
            You&apos;re all caught up. New reservations, cancellations, and special orders will show
            up here.
          </p>
        </div>
      ) : null}

      {items.length > 0 ? (
        <ul className="notification-list" data-testid="notification-list">
          {items.map((item) => (
            <li
              key={item.id}
              className={`notification${item.read_at ? "" : " notification--unread"}`}
            >
              <div className="notification__top">
                <Link className="notification__title" to={item.link} onClick={() => markRead.mutate(item.id)}>
                  {item.title}
                </Link>
                {item.read_at ? null : (
                  <button
                    type="button"
                    className="btn btn--ghost btn--small"
                    onClick={() => markRead.mutate(item.id)}
                    disabled={markRead.isPending}
                  >
                    Mark read
                  </button>
                )}
              </div>
              <p className="notification__body">{item.body}</p>
              <p className="notification__meta muted">
                {item.read_at ? "Read" : "Unread"} · {formatDateTime(item.created_at)}
              </p>
            </li>
          ))}
        </ul>
      ) : null}

      {notifications.hasNextPage ? (
        <button
          type="button"
          className="btn btn--ghost"
          onClick={() => void notifications.fetchNextPage()}
          disabled={notifications.isFetchingNextPage}
        >
          {notifications.isFetchingNextPage ? "Loading…" : "Load older notifications"}
        </button>
      ) : null}
    </div>
  );
}
