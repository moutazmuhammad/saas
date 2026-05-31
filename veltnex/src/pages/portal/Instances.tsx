import * as React from "react";
import { Link, useNavigate } from "react-router-dom";
import { Server, Plus, Search, Cpu, MemoryStick, HardDrive } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { StatusBadge } from "@/components/StatusBadge";
import { EmptyState } from "@/components/EmptyState";
import { Spinner } from "@/components/Spinner";
import { AlertBanner } from "@/components/AlertBanner";
import { useInstances } from "@/context/InstancesContext";
import { useSections } from "@/lib/useSections";
import { formatBytes } from "@/lib/format";
import { cn } from "@/lib/utils";

export default function Instances() {
  const { instances, loading, error } = useInstances();
  const navigate = useNavigate();
  const sections = useSections();
  // Send "Create instance" to whichever offering is live.
  const createTo = sections.hosting ? "/hosting" : "/services";
  const [query, setQuery] = React.useState("");

  const filtered = instances.filter(
    (i) =>
      i.name.toLowerCase().includes(query.toLowerCase()) ||
      (i.region || "").toLowerCase().includes(query.toLowerCase())
  );

  return (
    <div className="animate-fade-in">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Instances</h1>
          <p className="mt-1 text-sm text-muted">Manage and monitor all your Odoo deployments.</p>
        </div>
        <Button onClick={() => navigate(createTo)}>
          <Plus className="size-4" />
          New instance
        </Button>
      </div>

      {error && <AlertBanner className="mt-6" variant="danger" title="Couldn't load instances" description={error} />}

      <div className="relative mt-6 max-w-sm">
        <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted" />
        <Input
          className="pl-9"
          placeholder="Search instances…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>

      {loading && instances.length === 0 ? (
        <div className="mt-20 flex justify-center">
          <Spinner size="lg" label="Loading instances…" />
        </div>
      ) : filtered.length === 0 ? (
        <EmptyState
          className="mt-8"
          icon={Server}
          title={query ? "No matching instances" : "No instances yet"}
          description={query ? "Try a different search term." : "Deploy your first Odoo instance to get started."}
          action={!query && <Button onClick={() => navigate(createTo)}>Create instance</Button>}
        />
      ) : (
        <div className="mt-6 grid gap-4 md:grid-cols-2">
          {filtered.map((i) => {
            const live = i.state === "running";
            return (
              <Link key={i.id} to={`/my/instances/${i.id}`}>
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
          })}
        </div>
      )}
    </div>
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
