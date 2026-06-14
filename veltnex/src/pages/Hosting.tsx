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

/** Yearly saving vs paying month-by-month for a tier (amount + % off). */
function yearlySaving(t: { monthly: number; yearly: number }) {
  const annual = t.monthly * 12;
  const amount = t.yearly > 0 && t.yearly < annual ? annual - t.yearly : 0;
  const pct = amount > 0 ? Math.round((amount / annual) * 100) : 0;
  return { amount, pct };
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

  // Finalizing (subdomain, version, repo, payment) stays on Odoo. Carry the
  // chosen region so the checkout quotes the SAME region-scaled price.
  const goConfigure = (workers: number, storage: number, cycle: "monthly" | "yearly") => {
    const qs = new URLSearchParams({
      workers: String(workers),
      storage: String(storage),
      billing: cycle,
    });
    if (regionId != null) qs.set("region_id", String(regionId));
    window.location.href = `/hosting/configure?${qs.toString()}`;
  };

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
          <p className="text-sm font-medium text-primary-glow">Hosting</p>
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

        {/* Region picker — prices below reflect the selected region. Only
            shown when there's a genuine choice (> 1 available region). */}
        {showRegionPicker && (
          <div className="mb-10 flex flex-col items-center gap-3">
            <p className="flex items-center gap-1.5 text-sm font-medium text-muted">
              <Globe className="size-4 text-primary-glow" />
              Region
              {selectedRegion && selectedRegion.multiplier !== 1 && (
                <span className="rounded bg-card px-1.5 py-0.5 text-[11px] text-muted ring-1 ring-border">
                  ×{selectedRegion.multiplier.toFixed(2)} pricing
                </span>
              )}
            </p>
            <select
              value={regionId ?? ""}
              onChange={(e) => setRegionId(Number(e.target.value))}
              className="w-full max-w-xs cursor-pointer rounded-xl border border-border bg-card px-4 py-2.5 text-sm font-medium text-foreground outline-none ring-primary/40 transition-colors hover:border-primary/40 focus:ring-1"
            >
              {sortedRegions.map((r) => {
                const tag = (r.default || r.recommended)
                  ? " — Recommended"
                  : (r.budget || (cheapestRegion && r.id === cheapestRegion.id))
                    ? " — Budget"
                    : r.multiplier !== 1
                      ? ` (×${r.multiplier.toFixed(2)})`
                      : "";
                return (
                  <option key={r.id} value={r.id}>
                    {r.name}{tag}
                  </option>
                );
              })}
            </select>
            <p className="max-w-md text-center text-xs text-muted">
              Infrastructure costs differ between data centers, so prices are
              adjusted per region — we've pre-selected the recommended one for
              you, and marked the cheapest as “Budget”. Choose the region
              closest to your users for the best performance.
            </p>
          </div>
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
                        {maxSave.amount > 0
                          ? `Save up to ${money(maxSave.amount, maxSave.currency)}/yr`
                          : "Save"}
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
                    {(() => {
                      const s = yearlySaving(t);
                      if (s.amount <= 0) return null;
                      return config.cycle === "yearly" ? (
                        <p className="mt-2 inline-flex items-center gap-1.5 self-start rounded-lg bg-success/10 px-2.5 py-1 text-xs font-semibold text-success">
                          <Sparkles className="size-3.5" /> You save {money(s.amount, t.currency)}/yr · {s.pct}% off
                        </p>
                      ) : (
                        <p className="mt-2 text-xs text-muted">
                          Pay yearly and save {money(s.amount, t.currency)} ({s.pct}%)
                        </p>
                      );
                    })()}
                    <ul className="mt-5 space-y-2 text-sm text-muted">
                      <li className="flex items-center gap-2">
                        <Cpu className="size-4 text-primary-glow" /> {t.workers} dedicated workers
                      </li>
                      <li className="flex items-center gap-2">
                        <Users className="size-4 text-primary-glow" /> Recommended for {recommendedUsers(t.workers, usersPerWorkerMin, usersPerWorkerMax)} users
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

            <div className="mt-10 flex flex-col items-center gap-3 border-t border-border pt-8">
              <p className="text-sm text-muted">
                Need a different size? Build one with the exact workers and storage you want.
              </p>
              <Button variant="secondary" size="lg" onClick={() => setCustomize(true)}>
                <SlidersHorizontal className="size-4" />
                Build a custom plan
              </Button>
            </div>
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
              usersPerWorkerMin={usersPerWorkerMin}
              usersPerWorkerMax={usersPerWorkerMax}
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
        <div className="mx-auto w-full px-4 py-16 sm:px-6 lg:px-8">
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
