import { useNavigate } from "react-router-dom";
import {
  ArrowRight,
  GitBranch,
  Layers,
  ShieldCheck,
  Gauge,
  Check,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useSections } from "@/lib/useSections";

const FEATURES = [
  {
    icon: GitBranch,
    title: "Deploy from Git",
    desc: "Connect your repository — every push builds and deploys automatically.",
  },
  {
    icon: Layers,
    title: "Production, staging & dev",
    desc: "Spin up environments in one click, each on its own branch. Merge when ready.",
  },
  {
    icon: ShieldCheck,
    title: "Backups, SSL & uptime",
    desc: "Daily backups, free SSL and custom domains, 99.99% uptime — handled for you.",
  },
  {
    icon: Gauge,
    title: "Scale anytime",
    desc: "Adjust workers and storage whenever you need. Pay for exactly what you run.",
  },
];

const STEPS = [
  { n: 1, title: "Create a project", desc: "Name it and pick your size." },
  { n: 2, title: "Connect your repository", desc: "Link your Odoo modules from GitHub, GitLab or Bitbucket." },
  { n: 3, title: "Deploy", desc: "We provision, configure and run it — production is live." },
];

const INCLUDED = [
  "Daily automated backups",
  "Free SSL & custom domains",
  "Staging & development environments",
  "Zero-downtime module upgrades",
  "Streaming logs & live metrics",
  "24/7 expert support",
];

export default function Home() {
  const navigate = useNavigate();
  const sections = useSections();
  const deployTo = sections.hosting ? "/hosting" : "/services";

  return (
    <div className="animate-fade-in">
      {/* Hero */}
      <section className="border-b border-border">
        <div className="mx-auto max-w-3xl px-4 py-24 text-center sm:px-6 sm:py-28">
          <p className="text-sm font-medium text-primary">Managed Odoo hosting</p>
          <h1 className="mt-3 text-4xl font-bold tracking-tight sm:text-5xl">
            Deploy and run Odoo, the simple way
          </h1>
          <p className="mx-auto mt-5 max-w-xl text-lg text-muted">
            Push your code and get production, staging and development
            environments — with backups, SSL and scaling handled for you. No
            servers to manage.
          </p>
          <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
            <Button size="lg" onClick={() => navigate(deployTo)}>
              Deploy your Odoo
              <ArrowRight className="size-4" />
            </Button>
            <Button size="lg" variant="secondary" onClick={() => navigate("/login")}>
              Sign in
            </Button>
          </div>
          <p className="mt-4 text-sm text-muted">No server setup · Cancel anytime</p>
        </div>
      </section>

      {/* Features */}
      <section className="mx-auto max-w-5xl px-4 py-16 sm:px-6">
        <div className="grid gap-5 sm:grid-cols-2">
          {FEATURES.map((f) => (
            <Card key={f.title} className="p-6">
              <span className="flex size-10 items-center justify-center rounded-lg bg-primary/10 text-primary">
                <f.icon className="size-5" />
              </span>
              <h3 className="mt-4 text-base font-semibold">{f.title}</h3>
              <p className="mt-1.5 text-sm text-muted">{f.desc}</p>
            </Card>
          ))}
        </div>
      </section>

      {/* How it works */}
      <section className="border-y border-border bg-card/40">
        <div className="mx-auto max-w-5xl px-4 py-16 sm:px-6">
          <h2 className="text-center text-2xl font-semibold tracking-tight">Up and running in three steps</h2>
          <div className="mt-10 grid gap-6 sm:grid-cols-3">
            {STEPS.map((s) => (
              <div key={s.n} className="text-center">
                <span className="mx-auto flex size-10 items-center justify-center rounded-full bg-primary text-sm font-semibold text-primary-foreground">
                  {s.n}
                </span>
                <h3 className="mt-4 font-semibold">{s.title}</h3>
                <p className="mt-1.5 text-sm text-muted">{s.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Included */}
      <section className="mx-auto max-w-5xl px-4 py-16 sm:px-6">
        <h2 className="text-center text-2xl font-semibold tracking-tight">Everything included</h2>
        <div className="mx-auto mt-8 grid max-w-2xl gap-3 sm:grid-cols-2">
          {INCLUDED.map((item) => (
            <div key={item} className="flex items-center gap-3 text-sm">
              <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-success/15 text-success">
                <Check className="size-3" />
              </span>
              {item}
            </div>
          ))}
        </div>
      </section>

      {/* Final CTA */}
      <section className="border-t border-border">
        <div className="mx-auto max-w-3xl px-4 py-20 text-center sm:px-6">
          <h2 className="text-3xl font-bold tracking-tight">Ready to deploy?</h2>
          <p className="mx-auto mt-3 max-w-md text-muted">
            Create your first project in minutes.
          </p>
          <div className="mt-7">
            <Button size="lg" onClick={() => navigate(deployTo)}>
              Get started
              <ArrowRight className="size-4" />
            </Button>
          </div>
        </div>
      </section>
    </div>
  );
}
