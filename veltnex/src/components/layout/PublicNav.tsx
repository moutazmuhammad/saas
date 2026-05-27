import * as React from "react";
import { Link, NavLink, useNavigate } from "react-router-dom";
import { Menu, X, LayoutDashboard } from "lucide-react";
import { Logo } from "@/components/Logo";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/context/AuthContext";
import { cn } from "@/lib/utils";

const LINKS = [
  { to: "/services", label: "Services" },
  { to: "/hosting", label: "Hosting" },
  { to: "/docs", label: "Docs" },
];

export function PublicNav() {
  const [open, setOpen] = React.useState(false);
  const [scrolled, setScrolled] = React.useState(false);
  const { isAuthenticated } = useAuth();
  const navigate = useNavigate();

  React.useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    window.addEventListener("scroll", onScroll);
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <header
      className={cn(
        "sticky top-0 z-40 w-full transition-colors",
        scrolled
          ? "border-b border-border bg-background/80 backdrop-blur-xl"
          : "border-b border-transparent"
      )}
    >
      <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8">
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
          {isAuthenticated ? (
            <Button size="sm" onClick={() => navigate("/my")}>
              <LayoutDashboard className="size-4" />
              Dashboard
            </Button>
          ) : (
            <>
              <Link
                to="/login"
                className="text-sm font-medium text-muted transition-colors hover:text-foreground"
              >
                Sign in
              </Link>
              <Button size="sm" onClick={() => navigate("/services/register")}>
                Get started
              </Button>
            </>
          )}
        </div>

        <button
          className="rounded-md p-2 text-muted md:hidden"
          onClick={() => setOpen((o) => !o)}
          aria-label="Toggle menu"
        >
          {open ? <X className="size-5" /> : <Menu className="size-5" />}
        </button>
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
            <div className="flex flex-col gap-2 pt-3">
              {isAuthenticated ? (
                <Button onClick={() => navigate("/my")}>Dashboard</Button>
              ) : (
                <>
                  <Button variant="secondary" onClick={() => navigate("/login")}>
                    Sign in
                  </Button>
                  <Button onClick={() => navigate("/services/register")}>
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
