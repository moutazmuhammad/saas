import * as React from "react";
import { Link, NavLink, useLocation, useNavigate } from "react-router-dom";
import {
  Menu,
  X,
  LayoutDashboard,
  User,
  Server,
  LogOut,
  ChevronDown,
  LayoutGrid,
  type LucideIcon,
} from "lucide-react";
import { Logo } from "@/components/Logo";
import { Button } from "@/components/ui/button";
import { ThemeToggle } from "@/components/ThemeToggle";
import { useAuth } from "@/context/AuthContext";
import { useSections } from "@/lib/useSections";
import { cn } from "@/lib/utils";

const ALL_LINKS = [
  { to: "/services", label: "Services", section: "services" as const },
  { to: "/hosting", label: "Hosting", section: "hosting" as const },
  { to: "/docs", label: "Docs", section: null },
];

type MenuItem = { label: string; icon: LucideIcon; to: string; external: boolean };

// Shared account menu — kept identical to the QWeb header dropdown so the
// experience is the same across every page. "Profile" is an Odoo portal
// page, so it uses a full navigation; the rest are SPA routes.
const MENU: MenuItem[] = [
  { label: "Dashboard", icon: LayoutDashboard, to: "/my", external: false },
  { label: "Profile", icon: User, to: "/my/account", external: true },
  { label: "My Instances", icon: Server, to: "/my/instances", external: false },
];

// Internal (backend) users also get a link into the Odoo backend, mirroring
// the QWeb header's `t-if="has_group('base.group_user')"` Backend entry.
// `/odoo` is the Odoo web client root, so it's a full navigation.
const BACKEND_ITEM: MenuItem = {
  label: "Backend",
  icon: LayoutGrid,
  to: "/odoo",
  external: true,
};

export function PublicNav() {
  const [open, setOpen] = React.useState(false);
  const [scrolled, setScrolled] = React.useState(false);
  const { isAuthenticated, user, logout } = useAuth();
  const sections = useSections();
  const LINKS = ALL_LINKS.filter((l) => !l.section || sections[l.section]);
  // "Get started" sends people to sign up (works hosting-only too).
  const getStartedTo = "/register";
  const navigate = useNavigate();
  const location = useLocation();
  // Remember where the user is so signing in returns them here instead
  // of always dumping them on the dashboard. (Don't carry /login itself.)
  const current = location.pathname + location.search;
  const loginState = current.startsWith("/login") ? undefined : { from: current };
  // Backend users get the extra "Backend" link; portal users don't.
  const menuItems = user?.is_internal ? [...MENU, BACKEND_ITEM] : MENU;

  React.useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    window.addEventListener("scroll", onScroll);
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  const go = (item: MenuItem) => {
    if (item.external) window.location.href = item.to;
    else navigate(item.to);
  };

  const handleLogout = async () => {
    await logout();
    navigate("/");
  };

  return (
    <header
      className={cn(
        "sticky top-0 z-40 w-full transition-colors",
        scrolled
          ? "border-b border-border bg-background/80 backdrop-blur-xl"
          : "border-b border-transparent"
      )}
    >
      <div className="mx-auto flex h-16 w-full items-center justify-between px-4 sm:px-6 lg:px-8">
        <div className="flex items-center gap-8">
          <Logo />
          <nav className="hidden items-center gap-1 md:flex">
            {LINKS.map((l) => (
              <NavLink
                key={l.to}
                to={l.to}
                className={({ isActive }) =>
                  cn(
                    "rounded-md px-3 py-2 text-sm font-medium transition-colors",
                    isActive ? "text-foreground" : "text-muted hover:text-foreground"
                  )
                }
              >
                {l.label}
              </NavLink>
            ))}
          </nav>
        </div>

        <div className="hidden items-center gap-3 md:flex">
          <ThemeToggle />
          {isAuthenticated ? (
            <UserMenu
              initials={user?.initials || "U"}
              name={user?.name || "Account"}
              items={menuItems}
              onGo={go}
              onLogout={handleLogout}
            />
          ) : (
            <>
              <Link
                to="/login"
                state={loginState}
                className="text-sm font-medium text-muted transition-colors hover:text-foreground"
              >
                Sign in
              </Link>
              <Button size="sm" onClick={() => navigate(getStartedTo)}>
                Get started
              </Button>
            </>
          )}
        </div>

        <div className="flex items-center gap-2 md:hidden">
          <ThemeToggle />
          <button
            className="rounded-md p-2 text-muted"
            onClick={() => setOpen((o) => !o)}
            aria-label="Toggle menu"
          >
            {open ? <X className="size-5" /> : <Menu className="size-5" />}
          </button>
        </div>
      </div>

      {open && (
        <div className="border-t border-border bg-background md:hidden animate-fade-in">
          <nav className="space-y-1 px-4 py-4">
            {LINKS.map((l) => (
              <NavLink
                key={l.to}
                to={l.to}
                onClick={() => setOpen(false)}
                className={({ isActive }) =>
                  cn(
                    "block rounded-md px-3 py-2.5 text-sm font-medium",
                    isActive
                      ? "bg-card text-foreground"
                      : "text-muted hover:bg-card hover:text-foreground"
                  )
                }
              >
                {l.label}
              </NavLink>
            ))}
            <div className="mt-2 flex flex-col gap-1 border-t border-border pt-3">
              {isAuthenticated ? (
                <>
                  {menuItems.map((item) => (
                    <button
                      key={item.label}
                      onClick={() => {
                        setOpen(false);
                        go(item);
                      }}
                      className="flex items-center gap-2.5 rounded-md px-3 py-2.5 text-left text-sm font-medium text-muted hover:bg-card hover:text-foreground"
                    >
                      <item.icon className="size-4" />
                      {item.label}
                    </button>
                  ))}
                  <button
                    onClick={() => {
                      setOpen(false);
                      handleLogout();
                    }}
                    className="flex items-center gap-2.5 rounded-md px-3 py-2.5 text-left text-sm font-medium text-danger hover:bg-danger/10"
                  >
                    <LogOut className="size-4" />
                    Sign out
                  </button>
                </>
              ) : (
                <>
                  <Button variant="secondary" onClick={() => navigate("/login", { state: loginState })}>
                    Sign in
                  </Button>
                  <Button onClick={() => navigate(getStartedTo)}>
                    Get started
                  </Button>
                </>
              )}
            </div>
          </nav>
        </div>
      )}
    </header>
  );
}

function UserMenu({
  initials,
  name,
  items,
  onGo,
  onLogout,
}: {
  initials: string;
  name: string;
  items: MenuItem[];
  onGo: (item: MenuItem) => void;
  onLogout: () => void;
}) {
  const [open, setOpen] = React.useState(false);

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-2 rounded-lg border border-border bg-card px-2 py-1.5 text-sm transition-colors hover:bg-border/40"
      >
        <span className="flex size-7 items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground">
          {initials}
        </span>
        <span className="max-w-[120px] truncate font-medium">{name}</span>
        <ChevronDown className={cn("size-4 text-muted transition-transform", open && "rotate-180")} />
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute right-0 z-20 mt-2 w-52 overflow-hidden rounded-xl border border-border bg-card shadow-card animate-scale-in">
            {items.map((item) => (
              <button
                key={item.label}
                onClick={() => {
                  setOpen(false);
                  onGo(item);
                }}
                className="flex w-full items-center gap-2.5 px-3 py-2.5 text-left text-sm text-foreground transition-colors hover:bg-border/50"
              >
                <item.icon className="size-4 text-muted" />
                {item.label}
              </button>
            ))}
            <div className="border-t border-border" />
            <button
              onClick={() => {
                setOpen(false);
                onLogout();
              }}
              className="flex w-full items-center gap-2.5 px-3 py-2.5 text-left text-sm text-danger transition-colors hover:bg-danger/10"
            >
              <LogOut className="size-4" />
              Sign out
            </button>
          </div>
        </>
      )}
    </div>
  );
}
