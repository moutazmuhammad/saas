import { Link, useNavigate } from "react-router-dom";
import {
  ArrowRight,
  ShieldCheck,
  Zap,
  Activity,
  Database,
  Globe,
  Cpu,
  Lock,
  Gauge,
  CheckCircle2,
  Sparkles,
} from "lucide-react";
import * as React from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ServiceIcon } from "@/components/ServiceIcon";
import { api, type ApiService, type TrialInfo } from "@/lib/api";

const STATS = [
  { value: "99.99%", label: "Uptime SLA" },
  { value: "<40ms", label: "Avg. response" },
  { value: "12", label: "Global regions" },
  { value: "24/7", label: "Expert support" },
];

const FEATURES = [
  {
    icon: Zap,
    title: "Provision in seconds",
    description:
      "Spin up a production-ready Odoo instance with a single click. No infrastructure to manage.",
  },
  {
    icon: ShieldCheck,
    title: "Stable by design",
    description:
      "Isolated containers, automatic failover, and zero-downtime upgrades keep you online.",
  },
  {
    icon: Activity,
    title: "Live observability",
    description:
      "Real-time CPU, memory, and storage metrics with streaming logs for every instance.",
  },
  {
    icon: Database,
    title: "Effortless databases",
    description:
      "Create, clone, back up, and restore databases without touching a terminal.",
  },
  {
    icon: Gauge,
    title: "Scale on your terms",
    description:
      "Dial workers and storage up or down. You only ever see one simple monthly total.",
  },
  {
    icon: Lock,
    title: "Enterprise security",
    description:
      "SSO, audit logs, encrypted backups, and IP allow-lists — switched on by default.",
  },
];

export default function Home() {
  const navigate = useNavigate();
  const [services, setServices] = React.useState<ApiService[]>([]);
  const [trial, setTrial] = React.useState<TrialInfo | null>(null);

  React.useEffect(() => {
    api.services().then(setServices).catch(() => setServices([]));
    api.meta().then((m) => setTrial(m.trial)).catch(() => {});
  }, []);

  const trialReady = !!trial?.hosting_available && (trial?.days ?? 0) > 0;
  const startTrial = () => (window.location.href = "/hosting/configure?is_trial=1");

  return (
    <div className="animate-fade-in">
      {/* Hero */}
      <section className="relative overflow-hidden">
        <div className="pointer-events-none absolute inset-0 bg-grid-faint bg-[size:48px_48px] [mask-image:radial-gradient(ellipse_at_top,black,transparent_70%)]" />
        <div className="pointer-events-none absolute left-1/2 top-0 h-[480px] w-[820px] -translate-x-1/2 rounded-full bg-primary/20 blur-[140px]" />
        <div className="relative mx-auto max-w-7xl px-4 pb-24 pt-20 text-center sm:px-6 lg:px-8 lg:pt-28">
          <Link
            to="/services"
            className="inline-flex items-center gap-2 rounded-full border border-border bg-card/60 px-3 py-1 text-xs font-medium text-muted backdrop-blur transition-colors hover:text-foreground"
          >
            <span className="flex size-1.5 rounded-full bg-success" />
            Odoo 19 hosting is live
            <ArrowRight className="size-3" />
          </Link>
          <h1 className="mx-auto mt-6 max-w-4xl text-4xl font-bold tracking-tight sm:text-6xl">
            The Logic of <span className="text-primary-glow">Stability</span>
          </h1>
          <p className="mx-auto mt-6 max-w-2xl text-lg text-muted">
            VELTNEX is enterprise-grade managed hosting for Odoo. Provision,
            scale, and operate mission-critical instances — without the
            infrastructure headache.
          </p>
          <div className="mt-9 flex flex-col items-center justify-center gap-3 sm:flex-row">
            {trialReady ? (
              <Button size="lg" onClick={startTrial}>
                <Sparkles className="size-4" />
                Start your {trial?.days}-day free trial
              </Button>
            ) : (
              <Button size="lg" onClick={() => navigate("/hosting")}>
                Start building
                <ArrowRight />
              </Button>
            )}
            <Button
              size="lg"
              variant="secondary"
              onClick={() => navigate("/hosting")}
            >
              View hosting plans
            </Button>
          </div>
          {trialReady && (
            <p className="mt-3 text-xs text-muted">
              {trial?.days}-day free trial · no credit card required
            </p>
          )}

          {/* Floating dashboard preview */}
          <div className="relative mx-auto mt-16 max-w-4xl">
            <Card glass className="overflow-hidden p-1.5 shadow-glow">
              <div className="rounded-lg border border-border bg-background/80 p-5 text-left">
                <div className="flex items-center justify-between border-b border-border pb-4">
                  <div className="flex items-center gap-2">
                    <Globe className="size-4 text-primary-glow" />
                    <span className="font-mono text-sm">freightright.veltnex.app</span>
                  </div>
                  <span className="inline-flex items-center gap-1.5 rounded-full border border-success/30 bg-success/10 px-2.5 py-0.5 text-xs font-medium text-success">
                    <span className="size-1.5 rounded-full bg-success" />
                    Running
                  </span>
                </div>
                <div className="grid grid-cols-3 gap-4 pt-5">
                  {[
                    { icon: Cpu, label: "CPU", value: "34%" },
                    { icon: Activity, label: "Memory", value: "58%" },
                    { icon: Database, label: "Storage", value: "47%" },
                  ].map((m) => (
                    <div key={m.label} className="rounded-lg border border-border bg-card p-3">
                      <div className="flex items-center gap-2 text-muted">
                        <m.icon className="size-3.5" />
                        <span className="text-xs">{m.label}</span>
                      </div>
                      <p className="mt-2 text-xl font-semibold tabular-nums">{m.value}</p>
                    </div>
                  ))}
                </div>
              </div>
            </Card>
          </div>
        </div>
      </section>

      {/* Stats */}
      <section className="border-y border-border bg-card/30">
        <div className="mx-auto grid max-w-7xl grid-cols-2 gap-px px-4 sm:px-6 lg:grid-cols-4 lg:px-8">
          {STATS.map((s) => (
            <div key={s.label} className="py-10 text-center">
              <p className="text-3xl font-bold tracking-tight text-foreground">
                {s.value}
              </p>
              <p className="mt-1 text-sm text-muted">{s.label}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Features */}
      <section className="mx-auto max-w-7xl px-4 py-24 sm:px-6 lg:px-8">
        <div className="mx-auto max-w-2xl text-center">
          <h2 className="text-3xl font-bold tracking-tight sm:text-4xl">
            Everything you need to run Odoo in production
          </h2>
          <p className="mt-4 text-muted">
            A complete operations layer — so your team ships features instead of
            babysitting servers.
          </p>
        </div>
        <div className="mt-14 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map((f) => (
            <Card
              key={f.title}
              className="group p-6 transition-all hover:-translate-y-0.5 hover:border-primary/40"
            >
              <span className="flex size-11 items-center justify-center rounded-xl bg-primary/15 text-primary-glow transition-colors group-hover:bg-primary/25">
                <f.icon className="size-5" />
              </span>
              <h3 className="mt-5 text-lg font-semibold">{f.title}</h3>
              <p className="mt-2 text-sm text-muted">{f.description}</p>
            </Card>
          ))}
        </div>
      </section>

      {/* Services strip */}
      <section className="border-t border-border bg-card/30">
        <div className="mx-auto max-w-7xl px-4 py-24 sm:px-6 lg:px-8">
          <div className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-end">
            <div>
              <h2 className="text-3xl font-bold tracking-tight">One platform, every service</h2>
              <p className="mt-3 max-w-xl text-muted">
                From hosting to commerce to compliance — compose the stack your
                business needs.
              </p>
            </div>
            <Button variant="secondary" onClick={() => navigate("/services")}>
              Browse all services
              <ArrowRight />
            </Button>
          </div>
          <div className="mt-12 grid gap-5 md:grid-cols-2 lg:grid-cols-3">
            {services.slice(0, 3).map((s) => (
              <Link key={s.id} to={`/services/${s.id}`}>
                <Card className="group h-full p-6 transition-all hover:-translate-y-0.5 hover:border-primary/40">
                  <span className="flex size-11 items-center justify-center rounded-xl bg-primary/15 text-primary-glow">
                    <ServiceIcon icon={s.icon} className="size-5" />
                  </span>
                  <h3 className="mt-5 text-lg font-semibold">{s.name}</h3>
                  <p className="mt-2 text-sm text-muted">{s.tagline}</p>
                  <span className="mt-4 inline-flex items-center gap-1 text-sm font-medium text-primary-glow opacity-0 transition-opacity group-hover:opacity-100">
                    Learn more <ArrowRight className="size-3.5" />
                  </span>
                </Card>
              </Link>
            ))}
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="mx-auto max-w-7xl px-4 py-24 sm:px-6 lg:px-8">
        <Card glass className="relative overflow-hidden p-10 text-center sm:p-16">
          <div className="pointer-events-none absolute inset-0 bg-primary/10 blur-2xl" />
          <div className="relative">
            <h2 className="mx-auto max-w-2xl text-3xl font-bold tracking-tight sm:text-4xl">
              Ship on infrastructure that just stays up
            </h2>
            <p className="mx-auto mt-4 max-w-xl text-muted">
              Configure your plan in under a minute. No credit card required to
              explore the console.
            </p>
            <div className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
              <Button size="lg" onClick={() => navigate("/hosting")}>
                Configure your plan
                <ArrowRight />
              </Button>
              <Button size="lg" variant="outline" onClick={() => navigate("/docs")}>
                Read the docs
              </Button>
            </div>
            <div className="mt-8 flex flex-wrap items-center justify-center gap-x-6 gap-y-2 text-sm text-muted">
              {[
                ...(trialReady ? [`${trial?.days}-day free trial`] : ["No setup fees"]),
                "Cancel anytime",
                "Daily backups included",
              ].map((t) => (
                <span key={t} className="flex items-center gap-1.5">
                  <CheckCircle2 className="size-4 text-success" />
                  {t}
                </span>
              ))}
            </div>
          </div>
        </Card>
      </section>
    </div>
  );
}
