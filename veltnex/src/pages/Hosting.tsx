import * as React from "react";
import { ArrowRight, Check, ShieldCheck, Cpu, HardDrive, Globe, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { AlertBanner } from "@/components/AlertBanner";
import { PlanBuilder, type PlanConfig } from "@/components/PlanBuilder";
import { api, ApiError, type Meta, type PriceResult, type ApiTier } from "@/lib/api";
import { formatBytes } from "@/lib/format";
import { cn } from "@/lib/utils";

function money(amount: number, currency = "USD") {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    maximumFractionDigits: 2,
  }).format(amount);
}

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
  const [tiers, setTiers] = React.useState<ApiTier[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [config, setConfig] = React.useState<PlanConfig | null>(null);
  const [price, setPrice] = React.useState<PriceResult | null>(null);
  // When tiers exist we show cards by default; "customize" reveals the slider.
  const [customize, setCustomize] = React.useState(false);

  // Load limits/defaults + published tiers once.
  React.useEffect(() => {
    Promise.all([api.meta(), api.tiers("hosting").catch(() => [] as ApiTier[])])
      .then(([m, t]) => {
        setMeta(m);
        setTiers(t);
        const rec = t.find((x) => x.recommended) || t[0];
        setConfig({
          workers: rec ? rec.workers : m.hosting_config.min_workers,
          storageGb: rec ? rec.storage : m.hosting_config.min_storage,
          cycle: "monthly",
        });
        // No tiers configured -> behave exactly as before (slider only).
        if (!t.length) setCustomize(true);
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : "Could not load hosting plans."));
  }, []);

  // Recompute the (server-authoritative) slider price whenever the config changes.
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
  const goConfigure = (workers: number, storage: number, cycle: "monthly" | "yearly") => {
    const qs = new URLSearchParams({
      workers: String(workers),
      storage: String(storage),
      billing: cycle,
    });
    window.location.href = `/hosting/configure?${qs.toString()}`;
  };

  const setCycle = (cycle: "monthly" | "yearly") =>
    setConfig((c) => (c ? { ...c, cycle } : c));

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
        {config && tiers && tiers.length > 0 && !customize && (
          <div className="space-y-10">
            {/* Shared billing cycle toggle */}
            <div className="flex justify-center">
              <div className="inline-flex rounded-xl border border-border bg-card p-1">
                {(["monthly", "yearly"] as const).map((c) => (
                  <button
                    key={c}
                    onClick={() => setCycle(c)}
                    className={cn(
                      "flex items-center gap-1.5 rounded-lg px-5 py-2 text-sm font-medium capitalize transition-colors",
                      config.cycle === c
                        ? "bg-primary/20 text-foreground ring-1 ring-primary/40"
                        : "text-muted hover:text-foreground",
                    )}
                  >
                    {c}
                    {c === "yearly" && (
                      <span className="rounded bg-success/20 px-1.5 py-0.5 text-[10px] font-semibold text-success">
                        Save
                      </span>
                    )}
                  </button>
                ))}
              </div>
            </div>

            <div className="grid gap-6 md:grid-cols-3">
              {tiers.map((t) => {
                const amount = config.cycle === "yearly" ? t.yearly : t.monthly;
                const per = config.cycle === "yearly" ? "/yr" : "/mo";
                return (
                  <Card
                    key={t.id}
                    className={cn(
                      "relative flex flex-col p-6",
                      t.recommended && "ring-2 ring-primary",
                    )}
                  >
                    {t.recommended && (
                      <span className="absolute -top-3 left-1/2 -translate-x-1/2 whitespace-nowrap rounded-full bg-primary px-3 py-0.5 text-xs font-semibold text-white">
                        {t.badge || "Most popular"}
                      </span>
                    )}
                    <h3 className="text-lg font-semibold">{t.name}</h3>
                    <p className="mt-3 text-3xl font-bold">
                      {money(amount, t.currency)}
                      <span className="text-base font-normal text-muted">{per}</span>
                    </p>
                    <ul className="mt-5 space-y-2 text-sm text-muted">
                      <li className="flex items-center gap-2">
                        <Cpu className="size-4 text-primary-glow" /> {t.workers} dedicated workers
                      </li>
                      <li className="flex items-center gap-2">
                        <HardDrive className="size-4 text-primary-glow" /> {formatBytes(t.storage)} storage
                      </li>
                    </ul>
                    <Button
                      className="mt-6 w-full"
                      size="lg"
                      variant={t.recommended ? "default" : "secondary"}
                      onClick={() => goConfigure(t.workers, t.storage, config.cycle)}
                    >
                      Choose {t.name}
                      <ArrowRight />
                    </Button>
                  </Card>
                );
              })}
            </div>

            <p className="text-center text-sm text-muted">
              Need a different size?{" "}
              <button
                onClick={() => setCustomize(true)}
                className="font-medium text-primary-glow underline-offset-2 hover:underline"
              >
                Build a custom plan
              </button>
            </p>
          </div>
        )}

        {config && (customize || !tiers || tiers.length === 0) && (
          <div className="space-y-6">
            <PlanBuilder
              config={config}
              onChange={setConfig}
              limits={limits}
              price={price}
              currency={price?.currency || meta?.hosting_config.currency}
              footer={
                <Button
                  className="w-full"
                  size="lg"
                  onClick={() => goConfigure(config.workers, config.storageGb, config.cycle)}
                >
                  Continue to configure
                  <ArrowRight />
                </Button>
              }
            />
            {tiers && tiers.length > 0 && (
              <p className="text-center text-sm text-muted">
                <button
                  onClick={() => setCustomize(false)}
                  className="font-medium text-primary-glow underline-offset-2 hover:underline"
                >
                  ← Back to standard plans
                </button>
              </p>
            )}
          </div>
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
