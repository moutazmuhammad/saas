import * as React from "react";
import { ArrowRight, Check, ShieldCheck, Cpu, HardDrive, Globe, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { AlertBanner } from "@/components/AlertBanner";
import { PlanBuilder, type PlanConfig } from "@/components/PlanBuilder";
import { api, ApiError, type Meta, type PriceResult } from "@/lib/api";

const INCLUDED = [
  "Daily automated backups",
  "Zero-downtime upgrades",
  "Free SSL & custom domains",
  "99.99% uptime SLA",
  "Streaming logs & metrics",
  "24/7 expert support",
];

const SPECS = [
  { icon: Cpu, title: "Dedicated compute", desc: "Isolated CPU and memory per instance — no noisy neighbors." },
  { icon: HardDrive, title: "NVMe storage", desc: "Fast, redundant storage for databases and filestore." },
  { icon: Globe, title: "Global regions", desc: "Deploy close to your users." },
  { icon: ShieldCheck, title: "Hardened by default", desc: "Encrypted backups, audit logs, and IP allow-lists." },
];

export default function Hosting() {
  const [meta, setMeta] = React.useState<Meta | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [config, setConfig] = React.useState<PlanConfig | null>(null);
  const [price, setPrice] = React.useState<PriceResult | null>(null);

  // Load limits/defaults once.
  React.useEffect(() => {
    api
      .meta()
      .then((m) => {
        setMeta(m);
        setConfig({
          workers: m.hosting_config.min_workers,
          storageGb: m.hosting_config.min_storage,
          cycle: "monthly",
        });
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : "Could not load hosting plans."));
  }, []);

  // Recompute the (server-authoritative) price whenever the config changes.
  React.useEffect(() => {
    if (!config) return;
    let cancelled = false;
    setPrice(null);
    const t = setTimeout(() => {
      api
        .hostingCalculate(config.workers, config.storageGb, config.cycle)
        .then((p) => !cancelled && setPrice(p))
        .catch(() => !cancelled && setPrice(null));
    }, 180);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [config]);

  // Finalizing (subdomain, version, repo, payment) stays on Odoo.
  const continueToConfigure = () => {
    if (!config) return;
    const qs = new URLSearchParams({
      workers: String(config.workers),
      storage: String(config.storageGb),
      billing: config.cycle,
    });
    window.location.href = `/hosting/configure?${qs.toString()}`;
  };

  const limits = meta
    ? {
        workers: { min: meta.hosting_config.min_workers, max: meta.hosting_config.max_workers },
        storage: { min: meta.hosting_config.min_storage, max: meta.hosting_config.max_storage },
      }
    : { workers: { min: 1, max: 8 }, storage: { min: 5, max: 200 } };

  return (
    <div className="animate-fade-in">
      <section className="relative overflow-hidden border-b border-border">
        <div className="pointer-events-none absolute left-1/2 top-0 h-72 w-[700px] -translate-x-1/2 rounded-full bg-primary/15 blur-[120px]" />
        <div className="relative mx-auto max-w-7xl px-4 py-16 text-center sm:px-6 lg:px-8">
          <p className="text-sm font-medium text-primary-glow">Hosting</p>
          <h1 className="mx-auto mt-2 max-w-3xl text-4xl font-bold tracking-tight sm:text-5xl">
            Pay for exactly what you run
          </h1>
          <p className="mx-auto mt-4 max-w-2xl text-muted">
            Move the sliders to shape your instance. One transparent total —
            no per-resource math, no surprises on the invoice.
          </p>
          {meta?.trial.hosting_available && meta.trial.days > 0 && (
            <div className="mt-8 flex flex-col items-center gap-2">
              <Button
                size="lg"
                onClick={() => (window.location.href = "/hosting/configure?is_trial=1")}
              >
                <Sparkles className="size-4" />
                Start your {meta.trial.days}-day free trial
              </Button>
              <span className="text-xs text-muted">No credit card required.</span>
            </div>
          )}
        </div>
      </section>

      <section className="mx-auto max-w-7xl px-4 py-14 sm:px-6 lg:px-8">
        {error && (
          <AlertBanner className="mb-6" variant="danger" title="Couldn't load hosting plans" description={error} />
        )}
        {config && (
          <PlanBuilder
            config={config}
            onChange={setConfig}
            limits={limits}
            price={price}
            currency={price?.currency || meta?.hosting_config.currency}
            footer={
              <Button className="w-full" size="lg" onClick={continueToConfigure}>
                Continue to configure
                <ArrowRight />
              </Button>
            }
          />
        )}
      </section>

      <section className="border-y border-border bg-card/30">
        <div className="mx-auto max-w-7xl px-4 py-16 sm:px-6 lg:px-8">
          <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-4">
            {SPECS.map((s) => (
              <Card key={s.title} className="p-6">
                <span className="flex size-11 items-center justify-center rounded-xl bg-primary/15 text-primary-glow">
                  <s.icon className="size-5" />
                </span>
                <h3 className="mt-4 text-base font-semibold">{s.title}</h3>
                <p className="mt-2 text-sm text-muted">{s.desc}</p>
              </Card>
            ))}
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-3xl px-4 py-16 sm:px-6 lg:px-8">
        <h2 className="text-center text-2xl font-bold tracking-tight">Every plan includes</h2>
        <div className="mt-8 grid gap-3 sm:grid-cols-2">
          {INCLUDED.map((item) => (
            <div key={item} className="flex items-center gap-3 rounded-lg border border-border bg-card p-4 text-sm">
              <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-success/15 text-success">
                <Check className="size-3" />
              </span>
              {item}
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
