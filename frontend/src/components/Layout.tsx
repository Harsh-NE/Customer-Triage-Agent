import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../auth";
import { Button, cx } from "./ui";

const CUSTOMER_NAV = [{ to: "/chat", label: "New conversation", end: true }, { to: "/history", label: "My history", end: false }];
const ENGINEER_NAV = [
  { to: "/dashboard", label: "Dashboard", end: true }, { to: "/cases", label: "Escalated cases", end: false },
  { to: "/all-cases", label: "All cases", end: false }, { to: "/analytics", label: "Analytics", end: false },
  { to: "/cost", label: "Tokens & cost", end: false },
];

export default function Layout() {
  const { user, logout } = useAuth();
  const nav = user?.role === "engineer" ? ENGINEER_NAV : CUSTOMER_NAV;
  return (
    <div className="flex h-full flex-col md:flex-row">
      <aside className="flex shrink-0 flex-wrap items-center gap-x-3 border-b border-slate-200 bg-white md:w-56 md:flex-col md:flex-nowrap md:items-stretch md:gap-x-0 md:border-b-0 md:border-r">
        <div className="flex items-center gap-2 px-3 py-2 md:px-4 md:py-4">
          <span className="grid h-8 w-8 place-items-center rounded-lg bg-brand-600 text-sm font-bold text-white">D</span>
          <div className="leading-tight"><div className="text-sm font-semibold text-slate-900">Support Agent</div><div className="text-xs text-slate-500">{user?.role === "engineer" ? "Engineer console" : "Docker help"}</div></div>
        </div>
        <nav className="flex flex-1 gap-1 overflow-x-auto px-2 md:block md:space-y-0.5" aria-label="Main">
          {nav.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.end}
              className={({ isActive }) => cx("block shrink-0 whitespace-nowrap rounded-lg px-3 py-2 text-sm font-medium", isActive ? "bg-brand-50 text-brand-700" : "text-slate-600 hover:bg-slate-100")}>
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="flex items-center gap-2 p-2 md:block md:border-t md:border-slate-100 md:p-3">
          <div className="truncate text-sm text-slate-700 md:mb-2" title={user?.username}>{user?.username}</div>
          <Button variant="secondary" className="px-2.5 py-1.5 md:w-full md:px-3.5 md:py-2" onClick={logout}>Sign out</Button>
        </div>
      </aside>
      <main className="min-h-0 min-w-0 flex-1 overflow-y-auto"><Outlet /></main>
    </div>
  );
}
