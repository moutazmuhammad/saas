import * as React from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import {
  LayoutDashboard,
  Server,
  Receipt,
  LogOut,
  Menu,
  X,
  LifeBuoy,
  LayoutGrid,
  ChevronRight,
} from "lucide-react";
import { Logo } from "@/components/Logo";
import { useAuth } from "@/context/AuthContext";
import { useToast } from "@/context/ToastContext";
import { cn } from "@/lib/utils";

const NAV = [
  { to: "/my", label: "Overview", icon: LayoutDashboard, end: true },
  { to: "/my/instances", label: "Instances", icon: Server, end: false },
  { to: "/my/billing", label: "Billing", icon: Receipt, end: false },
];

export function PortalLayout() {
  const { user, logout } = useAuth();
  const toast = useToast();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const [mobileOpen, setMobileOpen] = React.useState(false);

  React.useEffect(() => {
    setMobileOpen(false);
    document.querySelector("main")?.scrollTo({ top: 0 });
  }, [pathname]);

  const handleLogout = () => {
    logout();
    toast.info("Signed out", "You've been securely logged out.");
    navigate("/");
  };

  const sidebar = (
    <div className="flex h-full flex-col">
      <div className="flex h-16 items-center border-b border-border px-5">
        <Logo />
      </div>
      <nav className="flex-1 space-y-1 p-3">
        {NAV.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors",
                isActive
                  ? "bg-primary/15 text-foreground"
                  : "text-muted hover:bg-card hover:text-foreground"
              )
            }
          >
            <item.icon className="size-4" />
            {item.label}
          </NavLink>
        ))}
      </nav>
      <div className="space-y-1 border-t border-border p-3">
        <NavLink
          to="/docs"
          className="flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium text-muted transition-colors hover:bg-card hover:text-foreground"
        >
          <LifeBuoy className="size-4" />
          Documentation
        </NavLink>
        {/* Internal (backend) users get a jump-link into the Odoo backend.
            `/odoo` is the Odoo web client root → full navigation. */}
        {user?.is_internal && (
          <a
            href="/odoo"
            className="flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium text-muted transition-colors hover:bg-card hover:text-foreground"
          >
            <LayoutGrid className="size-4" />
            Backend
          </a>
        )}
        <div className="mt-2 flex items-center gap-3 rounded-lg border border-border p-3">
          <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-primary text-sm font-semibold text-primary-foreground">
            {user?.initials}
          </span>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium">{user?.name}</p>
            <p className="truncate text-xs text-muted">{user?.company}</p>
          </div>
          <button
            onClick={handleLogout}
            className="rounded-md p-1.5 text-muted transition-colors hover:bg-border hover:text-danger"
            aria-label="Sign out"
          >
            <LogOut className="size-4" />
          </button>
        </div>
      </div>
    </div>
  );

  return (
    <div className="flex min-h-screen bg-background">
      {/* Desktop sidebar */}
      <aside className="fixed inset-y-0 left-0 hidden w-64 border-r border-border bg-card/40 lg:block">
        {sidebar}
      </aside>

      {/* Mobile drawer */}
      {mobileOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div
            className="absolute inset-0 bg-black/70 backdrop-blur-sm"
            onClick={() => setMobileOpen(false)}
          />
          <aside className="absolute inset-y-0 left-0 w-64 border-r border-border bg-card animate-slide-in-right">
            {sidebar}
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col lg:pl-64">
        <header className="sticky top-0 z-30 flex h-16 items-center gap-3 border-b border-border bg-background/80 px-4 backdrop-blur-xl lg:hidden">
          <button
            onClick={() => setMobileOpen(true)}
            className="rounded-md p-2 text-muted"
            aria-label="Open menu"
          >
            <Menu className="size-5" />
          </button>
          <Logo />
        </header>
        <main className="flex-1 overflow-y-auto">
          <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6 lg:px-10">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}

/** Small breadcrumb used at the top of portal sub-pages. */
export function PortalBreadcrumb({
  items,
}: {
  items: { label: string; to?: string }[];
}) {
  return (
    <nav className="mb-6 flex items-center gap-1.5 text-sm text-muted">
      {items.map((item, i) => (
        <span key={i} className="flex items-center gap-1.5">
          {i > 0 && <ChevronRight className="size-3.5 text-muted/50" />}
          {item.to ? (
            <NavLink to={item.to} className="transition-colors hover:text-foreground">
              {item.label}
            </NavLink>
          ) : (
            <span className="text-foreground">{item.label}</span>
          )}
        </span>
      ))}
    </nav>
  );
}
