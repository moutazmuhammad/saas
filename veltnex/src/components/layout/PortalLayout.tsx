import * as React from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import {
  Server,
  Receipt,
  Settings,
  LogOut,
  Search,
  LifeBuoy,
  LayoutGrid,
  ChevronRight,
  ChevronDown,
} from "lucide-react";
import { Logo } from "@/components/Logo";
import { ThemeToggle } from "@/components/ThemeToggle";
import { CommandPalette } from "@/components/CommandPalette";
import { NotificationsBell } from "@/components/NotificationsBell";
import { useAuth } from "@/context/AuthContext";
import { useToast } from "@/context/ToastContext";
import { cn } from "@/lib/utils";

const NAV = [
  { to: "/my/instances", label: "Projects", icon: Server },
  { to: "/my/billing", label: "Billing", icon: Receipt },
  { to: "/my/settings", label: "Settings", icon: Settings },
];

/** Small dropdown helper: button + panel that closes on outside-click / esc. */
function Dropdown({
  trigger,
  align = "left",
  width = "w-56",
  children,
}: {
  trigger: (open: boolean) => React.ReactNode;
  align?: "left" | "right";
  width?: string;
  children: (close: () => void) => React.ReactNode;
}) {
  const [open, setOpen] = React.useState(false);
  const ref = React.useRef<HTMLDivElement>(null);
  const { pathname } = useLocation();
  React.useEffect(() => setOpen(false), [pathname]);
  React.useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);
  return (
    <div ref={ref} className="relative">
      <button type="button" onClick={() => setOpen((o) => !o)}>
        {trigger(open)}
      </button>
      {open && (
        <div
          className={cn(
            "absolute z-50 mt-2 overflow-hidden rounded-xl border border-border bg-card p-1.5 shadow-2xl animate-fade-in",
            width,
            align === "right" ? "right-0" : "left-0",
          )}
        >
          {children(() => setOpen(false))}
        </div>
      )}
    </div>
  );
}

export function PortalLayout() {
  const { user, logout } = useAuth();
  const toast = useToast();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const [paletteOpen, setPaletteOpen] = React.useState(false);

  React.useEffect(() => {
    document.querySelector("main")?.scrollTo({ top: 0 });
  }, [pathname]);

  // Global ⌘K / Ctrl+K opens the command palette.
  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((o) => !o);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const handleLogout = () => {
    logout();
    toast.info("Signed out", "You've been securely logged out.");
    navigate("/");
  };

  const navItemClass = (active: boolean) =>
    cn(
      "flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm font-medium transition-colors",
      active ? "bg-primary/15 text-foreground" : "text-muted hover:bg-background/60 hover:text-foreground",
    );

  return (
    <div className="min-h-screen bg-background">
      {/* Top bar — a SINGLE menu holds all navigation + account actions, so the
          page's own left column (e.g. a project's branch tree) is the primary
          sidebar and there's no duplicated nav. */}
      <header className="sticky top-0 z-40 flex h-16 items-center gap-2 border-b border-border bg-background/80 px-4 backdrop-blur-xl sm:px-6">
        <Logo />

        <div className="ml-auto flex items-center gap-1.5">
          <button
            onClick={() => setPaletteOpen(true)}
            className="flex items-center gap-2 rounded-lg border border-border bg-background/40 px-2.5 py-1.5 text-sm text-muted transition-colors hover:text-foreground"
            aria-label="Search"
          >
            <Search className="size-4" />
            <span className="hidden md:inline">Search…</span>
            <kbd className="hidden rounded border border-border px-1.5 py-0.5 text-[10px] md:inline">⌘K</kbd>
          </button>
          <NotificationsBell />
          <ThemeToggle />

          {/* The one and only menu: navigation + account. */}
          <Dropdown
            align="right"
            width="w-60"
            trigger={(open) => (
              <span
                className={cn(
                  "flex items-center gap-1.5 rounded-full border border-border py-1 pl-1 pr-2 transition-colors hover:bg-card",
                  open && "bg-card",
                )}
              >
                <span className="flex size-7 items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground">
                  {user?.initials}
                </span>
                <ChevronDown className="size-3.5 text-muted" />
              </span>
            )}
          >
            {(close) => (
              <>
                <div className="px-3 py-2">
                  <p className="truncate text-sm font-medium">{user?.name}</p>
                  <p className="truncate text-xs text-muted">{user?.email}</p>
                </div>
                <div className="my-1 border-t border-border" />
                {NAV.map((item) => (
                  <button
                    key={item.to}
                    onClick={() => { close(); navigate(item.to); }}
                    className={navItemClass(pathname.startsWith(item.to))}
                  >
                    <item.icon className="size-4" />
                    {item.label}
                  </button>
                ))}
                <div className="my-1 border-t border-border" />
                <button onClick={() => { close(); navigate("/docs"); }} className={navItemClass(false)}>
                  <LifeBuoy className="size-4" />
                  Help &amp; support
                </button>
                {user?.is_internal && (
                  <a href="/odoo" className={navItemClass(false)}>
                    <LayoutGrid className="size-4" />
                    Backend
                  </a>
                )}
                <div className="my-1 border-t border-border" />
                <button
                  onClick={() => { close(); handleLogout(); }}
                  className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm font-medium text-danger transition-colors hover:bg-danger/10"
                >
                  <LogOut className="size-4" />
                  Sign out
                </button>
              </>
            )}
          </Dropdown>
        </div>
      </header>

      <main className="overflow-y-auto">
        <div className="mx-auto w-full px-4 py-6 sm:px-6 lg:px-8">
          <Outlet />
        </div>
      </main>

      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
    </div>
  );
}

/** Build environment-aware breadcrumb items for a project sub-page
 *  (Databases / Code / Logs / Backups). Keeps vocabulary consistent
 *  ("Projects → <project> → …") and routes children back through their
 *  project's Environments workspace. ``leaf`` is the current page name. */
export function envCrumbs(
  inst:
    | { id: number; name: string; environment: string; parent_id: number | false; is_hosting: boolean }
    | null,
  leaf: string,
  fallbackId: string | number,
): { label: string; to?: string }[] {
  const root = { label: "Projects", to: "/my/instances" };
  if (!inst) {
    return [root, { label: "Environment", to: `/my/instances/${fallbackId}` }, { label: leaf }];
  }
  if (inst.parent_id && inst.environment !== "production") {
    return [
      root,
      { label: "Environments", to: `/my/instances/${inst.parent_id}/environments?env=${inst.id}` },
      { label: inst.name, to: `/my/instances/${inst.id}` },
      { label: leaf },
    ];
  }
  return [
    root,
    { label: inst.name, to: inst.is_hosting ? `/my/instances/${inst.id}/environments` : `/my/instances/${inst.id}` },
    { label: leaf },
  ];
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
