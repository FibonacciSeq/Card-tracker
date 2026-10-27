import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../auth/context";

const NAV = [
  { to: "/", label: "Dashboard", end: true },
  { to: "/stock", label: "Stock", end: false },
  { to: "/reservations", label: "Reservations", end: false },
  { to: "/team", label: "Team", end: false, ownerOnly: true },
  { to: "/activity", label: "Activity", end: false, ownerOnly: true },
  { to: "/settings", label: "Settings", end: false },
];

export function Layout() {
  const { session, signOut } = useAuth();
  const shopName = session?.me.display_name ?? session?.me.email ?? "";
  const isOwner = session?.me.role === "owner";
  const navItems = NAV.filter((item) => !item.ownerOnly || isOwner);

  return (
    <div className="shell">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <aside className="sidebar">
        <div className="brand">
          <span className="brand__mark" aria-hidden="true">
            CT
          </span>
          <span className="brand__text">
            <strong>Card Tracker</strong>
            <small>Shop admin</small>
          </span>
        </div>

        <nav aria-label="Main">
          <ul className="nav">
            {navItems.map((item) => (
              <li key={item.to}>
                <NavLink to={item.to} end={item.end} className="nav__link">
                  {item.label}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>

        <div className="sidebar__footer">
          <p className="sidebar__user" title={session?.me.email}>
            {shopName}
          </p>
          <button type="button" className="btn btn--ghost btn--small" onClick={signOut}>
            Sign out
          </button>
        </div>
      </aside>

      <main id="main" className="main">
        <Outlet />
      </main>
    </div>
  );
}
