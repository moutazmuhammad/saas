import * as React from "react";
import { ArrowRight, Check, ShieldCheck, Cpu, HardDrive, Globe, Sparkles, SlidersHorizontal, Users } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { AlertBanner } from "@/components/AlertBanner";
import { PlanBuilder, type PlanConfig } from "@/components/PlanBuilder";
import {
  api,
  ApiError,
  type Meta,
  type PriceResult,
  type ProjectPriceResult,
  type ApiTier,
  type ApiRegion,
} from "@/lib/api";
import { formatBytes, recommendedUsers } from "@/lib/format";
import { cn } from "@/lib/utils";

function money(amount: number, currency = "USD") {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    maximumFractionDigits: 2,
  }).format(amount);
}

/** Turn a free-text project name into a valid subdomain slug. */
function toSubdomain(s: string) {
  return s
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9-]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 63);
}

/** Yearly saving vs paying month-by-month for a tier (amount + % off). */
function yearlySaving(t: { monthly: number; yearly: number }) {
  const annual = t.monthly * 12;
  const amount = t.yearly > 0 && t.yearly < annual ? annual - t.yearly : 0;
  const pct = amount > 0 ? Math.round((amount / annual) * 100) : 0;
  return { amount, pct };
}

function Stepper({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number;
  onChange: (n: number) => void;
}) {
  return (
    <div className="flex items-center justify-between rounded-lg border border-border p-3">
      <span className="text-sm font-medium">{label}</span>
      <div className="flex items-center gap-3">
        <button
          type="button"
          aria-label={`Decrease ${label}`}
          onClick={() => onChange(Math.max(0, value - 1))}
          disabled={value <= 0}
          className="flex size-8 items-center justify-center rounded-md border border-border text-lg leading-none text-muted transition-colors hover:text-foreground disabled:opacity-40"
        >
          −
        </button>
        <span className="w-6 text-center text-sm font-semibold tabular-nums">{value}</span>
        <button
          type="button"
          aria-label={`Increase ${label}`}
          onClick={() => onChange(value + 1)}
          className="flex size-8 items-center justify-center rounded-md border border-border text-lg leading-none text-muted transition-colors hover:text-foreground"
        >
          +
        </button>
      </div>
    </div>
  );
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
  // Region-aware pricing. `regionId === undefined` means "regions not loaded
  // yet"; `null` means "no regions configured" (x1.0). The picker only shows
  // when there's a real choice (> 1 available region).
  const [regions, setRegions] = React.useState<ApiRegion[]>([]);
  const [regionId, setRegionId] = React.useState<number | null | undefined>(undefined);
  // Cheapest entry price (region-aware) — the lowest of the slider floor and
  // any published tier — shown as "Starting from $X/mo".
  const [floorPrice, setFloorPrice] = React.useState<number | null>(null);
  const configInit = React.useRef(false);
  // Purchase wizard: 1 = name the project, 2 = choose specs, 3 = staging/dev.
  const [step, setStep] = React.useState(1);
  const [projectName, setProjectName] = React.useState("");
  const [stagingCount, setStagingCount] = React.useState(0);
  const [devCount, setDevCount] = React.useState(0);
  const [projectQuote, setProjectQuote] = React.useState<ProjectPriceResult | null>(null);

  // Load limits/defaults + available regions once.
  React.useEffect(() => {
    Promise.all([api.meta(), api.regions().catch(() => [] as ApiRegion[])])
      .then(([m, regs]) => {
        setMeta(m);
        setRegions(regs);
        // Pre-select the RECOMMENDED region (the API marks it `default`).
        // Fall back to the cheapest by multiplier, then the first region.
        const recommended = regs.find((r) => r.default || r.recommended);
        const cheapest = regs.length
          ? regs.reduce((a, b) => (b.multiplier < a.multiplier ? b : a))
          : null;
        const chosen = recommended ?? cheapest;
        setRegionId(chosen ? chosen.id : null);
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : "Could not load hosting plans."));
  }, []);

  // (Re)load published tiers whenever the chosen region changes — the prices
  // come back already scaled by that region's multiplier.
  React.useEffect(() => {
    if (regionId === undefined || !meta) return;
    let cancelled = false;
    api
      .tiers("hosting", regionId)
      .catch(() => [] as ApiTier[])
      .then((t) => {
        if (cancelled) return;
        setTiers(t);
        // Pick the initial config from the recommended tier exactly once;
        // region changes after that must NOT reset the customer's choice.
        if (!configInit.current) {
          configInit.current = true;
          const rec = t.find((x) => x.recommended) || t[0];
          setConfig({
            workers: rec ? rec.workers : meta.hosting_config.min_workers,
            storageGb: rec ? rec.storage : meta.hosting_config.min_storage,
            cycle: "monthly",
          });
          if (!t.length) setCustomize(true);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [regionId, meta]);

  // Cheapest entry price (region-aware): the slider floor at the minimum
  // config. Combined with the tier prices below to show "Starting from $X".
  React.useEffect(() => {
    if (!meta || regionId === undefined) return;
    let cancelled = false;
    api
      .hostingCalculate(
        meta.hosting_config.min_workers,
        meta.hosting_config.min_storage,
        "monthly",
        regionId,
      )
      .then((p) => !cancelled && setFloorPrice(p.total))
      .catch(() => !cancelled && setFloorPrice(null));
    return () => {
      cancelled = true;
    };
  }, [meta, regionId]);

  // Recompute the (server-authoritative) slider price whenever the config or
  // the region changes.
  React.useEffect(() => {
    if (!config || regionId === undefined) return;
    let cancelled = false;
    setPrice(null);
    const t = setTimeout(() => {
      api
        .hostingCalculate(config.workers, config.storageGb, config.cycle, regionId)
        .then((p) => !cancelled && setPrice(p))
        .catch(() => !cancelled && setPrice(null));
    }, 180);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [config, regionId]);

  const currency = price?.currency || meta?.hosting_config.currency || "USD";

  // Region-aware "starting from" — the lowest of the slider floor and any
  // published tier's monthly price.
  const startingFrom = React.useMemo(() => {
    const vals: number[] = [];
    if (tiers && tiers.length) vals.push(...tiers.map((t) => t.monthly));
    if (floorPrice != null) vals.push(floorPrice);
    return vals.length ? Math.min(...vals) : null;
  }, [tiers, floorPrice]);

  const selectedRegion = regions.find((r) => r.id === regionId) || null;
  const showRegionPicker = regions.length > 1;
  // Cheapest-first so the lowest entry price sits at the top of the
  // dropdown (and is the pre-selected default).
  const sortedRegions = React.useMemo(
    () => [...regions].sort((a, b) => a.multiplier - b.multiplier),
    [regions],
  );
  const cheapestRegion = sortedRegions[0] || null;

  // Largest yearly saving (as an AMOUNT) across tiers — drives the
  // "Save up to $X/yr" badge on the billing toggle.
  const maxSave = React.useMemo(() => {
    let best = { amount: 0, currency: currency };
    for (const t of tiers || []) {
      const s = yearlySaving(t);
      if (s.amount > best.amount) best = { amount: s.amount, currency: t.currency };
    }
    return best;
  }, [tiers, currency]);

  const subdomain = toSubdomain(projectName);

  // Pick a tier's specs and move on to the environments step.
  const selectTier = (workers: number, storage: number) => {
    setConfig((c) => (c ? { ...c, workers, storageGb: storage } : c));
    setStep(3);
  };

  // Final hand-off: name + specs + env counts → the Odoo configure/checkout
  // page (which collects version/domain/support/backup + payment). The
  // configure form prefills subdomain and the staging/dev counts.
  const goCheckout = () => {
    if (!config || !subdomain) return;
    const qs = new URLSearchParams({
      subdomain,
      workers: String(config.workers),
      storage: String(config.storageGb),
      billing: config.cycle,
      staging_count: String(stagingCount),
      dev_count: String(devCount),
    });
    if (regionId != null) qs.set("region_id", String(regionId));
    window.location.href = `/hosting/configure?${qs.toString()}`;
  };

  // Project total (plan + chosen staging/dev servers) for the env step.
  React.useEffect(() => {
    if (step !== 3 || !config || regionId === undefined) return;
    let cancelled = false;
    api
      .hostingCalculateProject({
        workers: config.workers,
        storage: config.storageGb,
        billing: config.cycle,
        region: regionId,
        staging_count: stagingCount,
        dev_count: devCount,
      })
      .then((p) => !cancelled && setProjectQuote(p))
      .catch(() => !cancelled && setProjectQuote(null));
    return () => {
      cancelled = true;
    };
  }, [step, config, regionId, stagingCount, devCount]);

  const setCycle = (cycle: "monthly" | "yearly") =>
    setConfig((c) => (c ? { ...c, cycle } : c));

  // Sizing hint: recommended users = workers × [min..max] (light → heavy
  // usage), tuned in Settings → "Users / worker: light → heavy". Shown on
  // tier cards and next to the workers slider.
  const usersPerWorkerMin = meta?.hosting_config.users_per_worker_min || 6;
  const usersPerWorkerMax =
    meta?.hosting_config.users_per_worker_max || usersPerWorkerMin;

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
        <div className="relative mx-auto w-full px-4 py-16 text-center sm:px-6 lg:px-8">
          <p className="text-sm font-medium text-primary">Hosting</p>
          <h1 className="mx-auto mt-2 max-w-3xl text-4xl font-bold tracking-tight sm:text-5xl">
            Pay for exactly what you run
          </h1>
          <p className="mx-auto mt-4 max-w-2xl text-muted">
            Move the sliders to shape your instance. One transparent total —
            no per-resource math, no surprises on the invoice.
          </p>
          {startingFrom != null && (
            <p className="mt-6 text-sm text-muted">
              Plans starting from{" "}
              <span className="text-2xl font-bold text-foreground align-middle">
                {money(startingFrom, currency)}
              </span>
              <span className="text-muted">/mo</span>
              {selectedRegion && showRegionPicker && (
                <span className="text-muted"> in {selectedRegion.name}</span>
              )}
            </p>
          )}
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

      <section className="mx-auto w-full px-4 py-14 sm:px-6 lg:px-8">
        {error && (
          <AlertBanner className="mb-6" variant="danger" title="Couldn't load hosting plans" description={error} />
        )}

        {!config ? (
          <p className="py-16 text-center text-sm text-muted">Loading plans…</p>
        ) : (
          <div className="mx-auto w-full max-w-5xl">
            {/* Step indicator */}
            <ol className="mb-10 flex items-center justify-center gap-1 sm:gap-3">
              {[
                { n: 1, label: "Name your project" },
                { n: 2, label: "Choose specs" },
                { n: 3, label: "Environments" },
              ].map((s, i, arr) => (
                <li key={s.n} className="flex items-center gap-2">
                  <button
                    type="button"
                    disabled={s.n > step}
                    onClick={() => s.n < step && setStep(s.n)}
                    className={cn(
                      "flex items-center gap-2 rounded-full px-2 py-1 text-sm transition-colors",
                      s.n < step && "cursor-pointer hover:bg-card",
                    )}
                  >
                    <span
                      className={cn(
                        "flex size-7 items-center justify-center rounded-full text-xs font-semibold",
                        step >= s.n ? "bg-primary text-primary-foreground" : "bg-card text-muted ring-1 ring-border",
                      )}
                    >
                      {s.n}
                    </span>
                    <span className={cn("hidden sm:inline", step === s.n ? "font-semibold text-foreground" : "text-muted")}>
                      {s.label}
                    </span>
                  </button>
                  {i < arr.length - 1 && <span className="h-px w-6 bg-border sm:w-10" />}
                </li>
              ))}
            </ol>

            {/* ── Step 1: name the project ── */}
            {step === 1 && (
              <Card className="mx-auto max-w-2xl p-6">
                <h2 className="text-lg font-semibold">Name your project</h2>
                <p className="mt-1 text-sm text-muted">
                  This identifies your project and becomes your default subdomain.
                </p>
                <div className="mt-5 space-y-2">
                  <label htmlFor="project-name" className="text-sm font-medium">Project name</label>
                  <input
                    id="project-name"
                    autoFocus
                    value={projectName}
                    onChange={(e) => setProjectName(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && subdomain && setStep(2)}
                    placeholder="My company ERP"
                    className="h-11 w-full rounded-lg border border-border bg-card px-3 text-sm outline-none ring-primary/40 focus:ring-1"
                  />
                  {subdomain && (
                    <p className="text-xs text-muted">
                      Subdomain: <span className="font-mono text-foreground">{subdomain}</span>
                    </p>
                  )}
                </div>

                {showRegionPicker && (
                  <div className="mt-5 space-y-2">
                    <label className="flex items-center gap-1.5 text-sm font-medium">
                      <Globe className="size-4 text-primary" /> Region
                    </label>
                    <select
                      value={regionId ?? ""}
                      onChange={(e) => setRegionId(Number(e.target.value))}
                      className="h-11 w-full cursor-pointer rounded-lg border border-border bg-card px-3 text-sm outline-none ring-primary/40 focus:ring-1"
                    >
                      {sortedRegions.map((r) => {
                        const tag = (r.default || r.recommended)
                          ? " — Recommended"
                          : (r.budget || (cheapestRegion && r.id === cheapestRegion.id))
                            ? " — Budget"
                            : r.multiplier !== 1 ? ` (×${r.multiplier.toFixed(2)})` : "";
                        return <option key={r.id} value={r.id}>{r.name}{tag}</option>;
                      })}
                    </select>
                  </div>
                )}

                <div className="mt-5 space-y-2">
                  <span className="text-sm font-medium">Billing</span>
                  <div className="inline-flex w-full rounded-xl border border-border bg-card p-1">
                    {(["monthly", "yearly"] as const).map((c) => (
                      <button
                        key={c}
                        onClick={() => setCycle(c)}
                        className={cn(
                          "flex flex-1 items-center justify-center gap-1.5 rounded-lg px-4 py-2 text-sm font-medium capitalize transition-colors",
                          config.cycle === c ? "bg-primary/20 text-foreground ring-1 ring-primary/40" : "text-muted hover:text-foreground",
                        )}
                      >
                        {c}
                        {c === "yearly" && maxSave.amount > 0 && (
                          <span className="rounded bg-success/20 px-1.5 py-0.5 text-[10px] font-semibold text-success">Save</span>
                        )}
                      </button>
                    ))}
                  </div>
                </div>

                <Button className="mt-6 w-full" size="lg" disabled={!subdomain} onClick={() => setStep(2)}>
                  Continue <ArrowRight />
                </Button>
              </Card>
            )}

            {/* ── Step 2: choose specs ── */}
            {step === 2 && (
              <div className="space-y-8">
                {tiers && tiers.length > 0 && !customize ? (
                  <>
                    <div className="grid gap-6 md:grid-cols-3">
                      {tiers.map((t) => {
                        const amount = config.cycle === "yearly" ? t.yearly : t.monthly;
                        const per = config.cycle === "yearly" ? "/yr" : "/mo";
                        return (
                          <Card key={t.id} className={cn("relative flex flex-col p-6", t.recommended && "ring-2 ring-primary")}>
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
                              <li className="flex items-center gap-2"><Cpu className="size-4 text-primary" /> {t.workers} dedicated workers</li>
                              <li className="flex items-center gap-2"><Users className="size-4 text-primary" /> Recommended for {recommendedUsers(t.workers, usersPerWorkerMin, usersPerWorkerMax)} users</li>
                              <li className="flex items-center gap-2"><HardDrive className="size-4 text-primary" /> {formatBytes(t.storage)} storage</li>
                            </ul>
                            <Button className="mt-6 w-full" size="lg" variant={t.recommended ? "default" : "secondary"} onClick={() => selectTier(t.workers, t.storage)}>
                              Choose {t.name} <ArrowRight />
                            </Button>
                          </Card>
                        );
                      })}
                    </div>
                    <div className="flex flex-col items-center gap-3 border-t border-border pt-8">
                      <p className="text-sm text-muted">Need a different size? Build one with the exact workers and storage you want.</p>
                      <Button variant="secondary" size="lg" onClick={() => setCustomize(true)}>
                        <SlidersHorizontal className="size-4" /> Build a custom plan
                      </Button>
                    </div>
                  </>
                ) : (
                  <div className="mx-auto max-w-2xl space-y-6">
                    <PlanBuilder
                      config={config}
                      onChange={setConfig}
                      limits={limits}
                      price={price}
                      currency={price?.currency || meta?.hosting_config.currency}
                      usersPerWorkerMin={usersPerWorkerMin}
                      usersPerWorkerMax={usersPerWorkerMax}
                      footer={
                        <Button className="w-full" size="lg" onClick={() => setStep(3)}>
                          Continue <ArrowRight />
                        </Button>
                      }
                    />
                    {tiers && tiers.length > 0 && (
                      <p className="text-center text-sm text-muted">
                        <button onClick={() => setCustomize(false)} className="font-medium text-primary underline-offset-2 hover:underline">
                          ← Back to standard plans
                        </button>
                      </p>
                    )}
                  </div>
                )}
                <p className="text-center text-sm text-muted">
                  <button onClick={() => setStep(1)} className="font-medium text-primary underline-offset-2 hover:underline">← Back</button>
                </p>
              </div>
            )}

            {/* ── Step 3: staging & development ── */}
            {step === 3 && (
              <Card className="mx-auto max-w-2xl p-6">
                <h2 className="text-lg font-semibold">Staging &amp; Development servers</h2>
                <p className="mt-1 text-sm text-muted">
                  Production is always included. Add extra Staging and Development
                  servers (lowest spec) — you can add more any time later.
                </p>

                <div className="mt-5 space-y-3">
                  <Stepper label="Staging servers" value={stagingCount} onChange={setStagingCount} />
                  <Stepper label="Development servers" value={devCount} onChange={setDevCount} />
                </div>

                <div className="mt-6 space-y-1.5 rounded-lg border border-border bg-card/50 p-4 text-sm">
                  <div className="flex justify-between"><span className="text-muted">Production plan</span><span className="font-medium">{money(price?.total ?? 0, currency)}{config.cycle === "yearly" ? "/yr" : "/mo"}</span></div>
                  {projectQuote && (stagingCount + devCount) > 0 && (
                    <div className="flex justify-between"><span className="text-muted">{stagingCount + devCount} × env server</span><span className="font-medium">{money(projectQuote.env_total, currency)}{config.cycle === "yearly" ? "/yr" : "/mo"}</span></div>
                  )}
                  <div className="flex justify-between border-t border-border pt-1.5 text-base font-semibold">
                    <span>Total</span>
                    <span>{money(projectQuote?.project_total ?? price?.total ?? 0, currency)}{config.cycle === "yearly" ? "/yr" : "/mo"}</span>
                  </div>
                </div>

                <div className="mt-6 flex items-center gap-3">
                  <Button variant="secondary" onClick={() => setStep(2)}>← Back</Button>
                  <Button className="flex-1" size="lg" onClick={goCheckout}>
                    Continue to checkout <ArrowRight />
                  </Button>
                </div>
              </Card>
            )}
          </div>
        )}
      </section>

      <section className="border-y border-border bg-card/30">
        <div className="mx-auto w-full px-4 py-16 sm:px-6 lg:px-8">
          <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-4">
            {SPECS.map((s) => (
              <Card key={s.title} className="p-6">
                <span className="flex size-11 items-center justify-center rounded-xl bg-primary/15 text-primary">
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
