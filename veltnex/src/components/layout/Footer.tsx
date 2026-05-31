import { Link } from "react-router-dom";
import { Github, Twitter, Linkedin } from "lucide-react";
import { Logo } from "@/components/Logo";
import { useSections } from "@/lib/useSections";

export function Footer() {
  const sections = useSections();
  // "Get started" sends people to sign up (works hosting-only too).
  const getStartedTo = "/register";
  const COLUMNS = [
    {
      title: "Product",
      links: [
        sections.services && { label: "Services", to: "/services" },
        sections.hosting && { label: "Hosting", to: "/hosting" },
        sections.hosting && { label: "Configure", to: "/hosting/configure" },
        { label: "Docs", to: "/docs" },
      ].filter(Boolean) as { label: string; to: string }[],
    },
    {
      title: "Company",
      links: [
        { label: "About", to: "/" },
        { label: "Customers", to: "/" },
        { label: "Careers", to: "/" },
        { label: "Contact", to: "/" },
      ],
    },
    {
      title: "Account",
      links: [
        { label: "Sign in", to: "/login" },
        { label: "Get started", to: getStartedTo },
        { label: "Dashboard", to: "/my" },
        { label: "Invoices", to: "/my/invoices" },
      ],
    },
  ];
  return (
    <footer className="border-t border-border bg-background">
      <div className="mx-auto max-w-7xl px-4 py-14 sm:px-6 lg:px-8">
        <div className="grid gap-10 md:grid-cols-[1.5fr_repeat(3,1fr)]">
          <div>
            <Logo />
            <p className="mt-4 max-w-xs text-sm text-muted">
              The Logic of Stability. Enterprise-grade managed hosting for Odoo,
              built for teams that can't afford downtime.
            </p>
            <div className="mt-5 flex gap-3">
              {[Twitter, Github, Linkedin].map((Icon, i) => (
                <a
                  key={i}
                  href="#"
                  className="flex size-9 items-center justify-center rounded-lg border border-border text-muted transition-colors hover:border-border/50 hover:text-foreground"
                  aria-label="Social link"
                >
                  <Icon className="size-4" />
                </a>
              ))}
            </div>
          </div>
          {COLUMNS.map((col) => (
            <div key={col.title}>
              <h4 className="text-sm font-semibold">{col.title}</h4>
              <ul className="mt-4 space-y-3">
                {col.links.map((l) => (
                  <li key={l.label}>
                    <Link
                      to={l.to}
                      className="text-sm text-muted transition-colors hover:text-foreground"
                    >
                      {l.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
        <div className="mt-12 flex flex-col items-center justify-between gap-4 border-t border-border pt-6 sm:flex-row">
          <p className="text-xs text-muted">
            © {new Date().getFullYear()} VELTNEX, Inc. All rights reserved.
          </p>
          <p className="text-xs text-muted">
            Status: <span className="text-success">All systems operational</span>
          </p>
        </div>
      </div>
    </footer>
  );
}
