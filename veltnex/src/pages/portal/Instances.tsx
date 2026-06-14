import * as React from "react";
import { Link, useNavigate } from "react-router-dom";
import { Server, Plus, Search, Cpu, MemoryStick, HardDrive, Boxes, Wrench } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { StatusBadge } from "@/components/StatusBadge";
import { EmptyState } from "@/components/EmptyState";
import { Spinner } from "@/components/Spinner";
import { AlertBanner } from "@/components/AlertBanner";
import { PageHeader } from "@/components/PageHeader";
import { useInstances } from "@/context/InstancesContext";
import { useSections } from "@/lib/useSections";
import { formatBytes } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { ApiInstance } from "@/lib/api";

export default function Instances() {
  const { instances, loading, error } = useInstances();
  const navigate = useNavigate();
  const sections = useSections();
  // Send "Create instance" to whichever offering is live.
  const createTo = sections.hosting ? "/hosting" : "/services";
  const [query, setQuery] = React.useState("");
  const [onlyRunning, setOnlyRunning] = React.useState(false);

  const runningTotal = instances.filter((i) => i.state === "running").length;

  const filtered = instances.filter((i) => {
    const q = query.toLowerCase();
    const matchesQuery =
      i.name.toLowerCase().includes(q) || (i.region || "").toLowerCase().includes(q);
    return matchesQuery && (!onlyRunning || i.state === "running");
  });
  // Separate self-managed hosting from managed services.
  const hosting = filtered.filter((i) => i.is_hosting);
  const services = filtered.filter((i) => !i.is_hosting);

  return (
    <div className="animate-fade-in">
      <PageHeader
        title="Projects"
        subtitle="Manage and monitor all your Odoo projects."
        actions={
          <Button onClick={() => navigate(createTo)}>
            <Plus className="size-4" />
            Create project
          </Button>
        }
      />

      {error && <AlertBanner className="mt-6" variant="danger" title="Couldn't load instances" description={error} />}

      {/* Search + running filter */}
      <div className="mt-6 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="relative max-w-sm flex-1">
          <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted" />
          <Input
            className="pl-9"
            placeholder="Search projects…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <div className="inline-flex rounded-xl border border-border bg-card p-1">
          {([
            { key: false, label: "All" },
            { key: true, label: `Running (${runningTotal})` },
          ] as const).map((opt) => (
            <button
              key={String(opt.key)}
              onClick={() => setOnlyRunning(opt.key)}
              className={cn(
                "rounded-lg px-4 py-1.5 text-sm font-medium transition-colors",
                onlyRunning === opt.key
                  ? "bg-primary/20 text-foreground ring-1 ring-primary/40"
                  : "text-muted hover:text-foreground",
              )}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {loading && instances.length === 0 ? (
        <div className="mt-20 flex justify-center">
          <Spinner size="lg" label="Loading instances…" />
        </div>
      ) : filtered.length === 0 ? (
        <EmptyState
          className="mt-8"
          icon={Server}
          title={query || onlyRunning ? "No matching instances" : "No instances yet"}
          description={
            query || onlyRunning
              ? "Try a different search term or filter."
              : "Deploy your first Odoo instance to get started."
          }
          action={!query && !onlyRunning && <Button onClick={() => navigate(createTo)}>Create instance</Button>}
        />
      ) : (
        <div className="mt-8 space-y-10">
          <Section title="Hosting" icon={Wrench} hint="Self-managed" items={hosting} />
          <Section title="Services" icon={Boxes} hint="Managed apps" items={services} />
        </div>
      )}
    </div>
  );
}

function Section({
  title,
  icon: Icon,
  hint,
  items,
}: {
  title: string;
  icon: typeof Server;
  hint: string;
  items: ApiInstance[];
}) {
  if (items.length === 0) return null;
  return (
    <section>
      <div className="flex items-center gap-2">
        <span className="flex size-7 items-center justify-center rounded-lg bg-primary/15 text-primary-glow">
          <Icon className="size-4" />
        </span>
        <h2 className="font-semibold">{title}</h2>
        <span className="rounded-full border border-border px-2 py-0.5 text-xs text-muted">{items.length}</span>
        <span className="text-xs text-muted">· {hint}</span>
      </div>
      <div className="mt-4 grid gap-4 md:grid-cols-2">
        {items.map((i) => (
          <InstanceCard key={i.id} instance={i} />
        ))}
      </div>
    </section>
  );
}

function InstanceCard({ instance: i }: { instance: ApiInstance }) {
  const live = i.state === "running";
  // Hosting instances are PROJECTS — open the Odoo.sh-style workspace.
  // Managed services have no environments, so they open their detail page.
  const to = i.is_hosting
    ? `/my/instances/${i.id}/environments`
    : `/my/instances/${i.id}`;
  return (
    <Link to={to}>
      <Card className="group p-5 transition-all hover:-translate-y-0.5 hover:border-primary/40">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="truncate font-semibold">{i.name}</p>
            <p className="truncate font-mono text-xs text-muted">{i.domain}</p>
          </div>
          <StatusBadge status={i.state} label={i.state_label} />
        </div>
        <p className="mt-3 text-sm text-muted">{i.region || "—"}</p>
        <div className="mt-4 grid grid-cols-3 gap-3">
          <Metric icon={Cpu} label="CPU" value={`${i.usage.cpu}%`} active={live} />
          <Metric icon={MemoryStick} label="RAM" value={`${i.usage.ram}%`} active={live} />
          <Metric icon={HardDrive} label="Disk" value={`${i.usage.storage}%`} active />
        </div>
        <div className="mt-4 flex items-center justify-between border-t border-border pt-3 text-xs text-muted">
          <span>{i.workers} workers · {formatBytes(i.storage_gb)}</span>
          <span className="capitalize">{i.billing_cycle}</span>
        </div>
      </Card>
    </Link>
  );
}

function Metric({
  icon: Icon,
  label,
  value,
  active,
}: {
  icon: typeof Cpu;
  label: string;
  value: string;
  active: boolean;
}) {
  return (
    <div className="rounded-lg border border-border bg-background/50 p-2.5">
      <div className="flex items-center gap-1 text-[11px] text-muted">
        <Icon className="size-3" />
        {label}
      </div>
      <p className={cn("mt-1 text-sm font-semibold tabular-nums", !active && "text-muted")}>
        {active ? value : "—"}
      </p>
    </div>
  );
}
