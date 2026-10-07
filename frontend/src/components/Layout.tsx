import { NavLink, Outlet } from "react-router-dom";

import { useMe } from "../api/hooks";
import { useAuth } from "../auth/context";

const linkClass = ({ isActive }: { isActive: boolean }) =>
  `rounded px-3 py-1.5 text-sm font-medium ${
    isActive ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-200"
  }`;

export function Layout() {
  const { name, signOut } = useAuth();
  const me = useMe();

  return (
    <div className="min-h-screen">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl items-center gap-4 px-6 py-3">
          <span className="font-semibold">Incident Manager</span>
          <nav className="flex gap-1">
            <NavLink to="/" end className={linkClass}>
              Incidents
            </NavLink>
            <NavLink to="/on-call" className={linkClass}>
              On-call
            </NavLink>
          </nav>
          <div className="ml-auto flex items-center gap-3 text-sm text-slate-600">
            <span>
              {name}
              {me.data && <span className="text-slate-400"> · {me.data.roles.join(", ")}</span>}
            </span>
            <button className="underline" onClick={signOut}>
              Sign out
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-6 py-6">
        <Outlet />
      </main>
    </div>
  );
}
