import * as React from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  Play,
  Square,
  RotateCw,
  Database,
  ScrollText,
  Archive,
  Cpu,
  MemoryStick,
  HardDrive,
  ExternalLink,
  Globe,
  ServerCrash,
  CreditCard,
  ArrowUpCircle,
  Clock,
} from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ActionButton } from "@/components/ActionButton";
import { StatusBadge } from "@/components/StatusBadge";
import { AlertBanner } from "@/components/AlertBanner";
import { InfoCard } from "@/components/InfoCard";
import { EmptyState } from "@/components/EmptyState";
import { Spinner } from "@/components/Spinner";
import { PortalBreadcrumb } from "@/components/layout/PortalLayout";
import { useInstances } from "@/context/InstancesContext";
import { useToast } from "@/context/ToastContext";
import { api, ApiError, type ApiInstance } from "@/lib/api";
import { formatBytes, formatDate } from "@/lib/format";
import { cn } from "@/lib/utils";

const TRANSITIONAL = new Set(["provisioning", "pending_provision", "paid", "pending_payment"]);

export default function InstanceDetail() {
  const { id = "" } = useParams();
  const instanceId = Number(id);
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const toast = useToast();
  const { runAction, patch } = useInstances();

  const [instance, setInstance] = React.useState<ApiInstance | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [pending, setPending] = React.useState<"start" | "stop" | "restart" | null>(null);

  const load = React.useCallback(async () => {
    try {
      const data = await api.instance(instanceId, params.get("access_token") || undefined);
      setInstance(data);
      patch(data);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Instance not found.");
    }
  }, [instanceId, params, patch]);

  React.useEffect(() => {
    load();
  }, [load]);

  // Notify on payment return.
  React.useEffect(() => {
    if (params.get("payment") === "success") {
      toast.success("Payment received", "Your instance is being provisioned.");
    }
  }, [params, toast]);

  // Live status polling (state + usage).
  React.useEffect(() => {
    if (!instance) return;
    const fast = TRANSITIONAL.has(instance.state);
    if (!fast && instance.state !== "running") return;
    const t = setInterval(async () => {
      try {
        const s = await api.instanceStatus(instanceId);
        setInstance((prev) =>
          prev ? { ...prev, state: s.state, state_label: s.state_label, url: s.url || prev.url, usage: s.usage || prev.usage } : prev
        );
      } catch {
        /* transient */
      }
    }, fast ? 4000 : 10000);
    return () => clearInterval(t);
  }, [instance, instanceId]);

  if (error) {
    return (
      <EmptyState
        className="mt-10"
        icon={ServerCrash}
        title="Instance not found"
        description="This instance may have been removed or you don't have access."
        action={<Button onClick={() => navigate("/my/instances")}>Back to instances</Button>}
      />
    );
  }

  if (!instance) {
    return (
      <div className="flex min-h-[50vh] items-center justify-center">
        <Spinner size="lg" label="Loading instance…" />
      </div>
    );
  }

  const isRunning = instance.state === "running";
  const isBusy = TRANSITIONAL.has(instance.state);
  const isSuspended = instance.state === "suspended";

  const run = async (action: "start" | "stop" | "restart", label: string) => {
    setPending(action);
    try {
      await runAction(instanceId, action);
      await load();
      toast.success(label, instance.name);
    } catch (e) {
      toast.error("Action failed", e instanceof ApiError ? e.message : "Please try again.");
    } finally {
      setPending(null);
    }
  };

  const subnav = [
    ...(instance.is_hosting
      ? [{ to: `/my/instances/${id}/databases`, label: "Databases", icon: Database }]
      : []),
    { to: `/my/instances/${id}/logs`, label: "Logs", icon: ScrollText },
    { to: `/my/instances/${id}/backups`, label: "Backups", icon: Archive },
  ];

  return (
    <div className="animate-fade-in">
      <PortalBreadcrumb items={[{ label: "Instances", to: "/my/instances" }, { label: instance.name }]} />

      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold tracking-tight">{instance.name}</h1>
            <StatusBadge status={instance.state} label={instance.state_label} />
          </div>
          {instance.url ? (
            <a
              href={instance.url}
              target="_blank"
              rel="noreferrer"
              className="mt-1.5 inline-flex items-center gap-1.5 font-mono text-sm text-muted transition-colors hover:text-primary-glow"
            >
              <Globe className="size-3.5" />
              {instance.domain}
              <ExternalLink className="size-3" />
            </a>
          ) : (
            <span className="mt-1.5 inline-flex items-center gap-1.5 font-mono text-sm text-muted">
              <Globe className="size-3.5" />
              {instance.domain}
            </span>
          )}
        </div>

        <div className="flex flex-wrap gap-2">
          {isRunning ? (
            <>
              <ActionButton
                variant="secondary"
                icon={RotateCw}
                loading={pending === "restart"}
                loadingText="Restarting…"
                disabled={!!pending}
                onClick={() => run("restart", "Instance restarted")}
              >
                Restart
              </ActionButton>
              <ActionButton
                variant="danger"
                icon={Square}
                loading={pending === "stop"}
                loadingText="Stopping…"
                disabled={!!pending}
                onClick={() => run("stop", "Instance stopped")}
              >
                Stop
              </ActionButton>
            </>
          ) : (
            <ActionButton
              icon={Play}
              loading={pending === "start" || isBusy}
              loadingText={isBusy ? "Provisioning…" : "Starting…"}
              disabled={!!pending || isBusy || isSuspended}
              onClick={() => run("start", "Instance started")}
            >
              Start
            </ActionButton>
          )}
        </div>
      </div>

      {isBusy && (
        <AlertBanner
          className="mt-6"
          variant="info"
          title="Provisioning in progress"
          description="Your instance is being prepared. Resources come online automatically — this page updates itself."
        />
      )}
      {isSuspended && (
        <AlertBanner
          className="mt-6"
          variant="warning"
          title="This instance is suspended"
          description="Suspended instances can't be started until billing is resolved."
          action={
            <Button size="sm" variant="secondary" onClick={() => navigate("/my/billing")}>
              View invoices
            </Button>
          }
        />
      )}
      {instance.has_unpaid_invoice && (
        <AlertBanner
          className="mt-6"
          variant="warning"
          title="You have an unpaid invoice for this instance"
          description="Complete payment to keep your instance active."
          action={
            <Button size="sm" onClick={() => (window.location.href = instance.checkout_url || "/my/billing")}>
              <CreditCard className="size-4" />
              Pay now
            </Button>
          }
        />
      )}

      <div className="mt-6 grid gap-4 lg:grid-cols-3">
        <UsageCard icon={Cpu} label="CPU" value={instance.usage.cpu} active={isRunning} />
        <UsageCard icon={MemoryStick} label="Memory" value={instance.usage.ram} active={isRunning} />
        <UsageCard icon={HardDrive} label="Storage" value={instance.usage.storage} active />
      </div>

      <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <InfoCard label="Region" value={<span className="text-base">{(instance.region || "—").split(" · ").pop()}</span>} />
        <InfoCard label="Version" value={<span className="text-base">{instance.version || "—"}</span>} />
        <InfoCard label="Plan" value={<span className="text-base">{instance.plan_name || `${instance.workers}W`}</span>} hint={`${instance.workers} workers`} />
        <InfoCard label="Storage" value={formatBytes(instance.storage_gb)} hint={instance.created ? `Since ${formatDate(instance.created)}` : undefined} />
      </div>

      <Card className="mt-4 flex flex-col gap-4 p-5 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="text-sm text-muted">Current plan</p>
          <p className="mt-0.5 text-base font-semibold">{instance.plan_name || `${instance.workers} workers`}</p>
          <p className="mt-1 text-xs text-muted">
            {instance.workers} workers · {formatBytes(instance.storage_gb)} · billed {instance.billing_cycle}
          </p>
          {instance.pending_plan && (
            <p className="mt-2 inline-flex items-center gap-1.5 text-xs text-warning">
              <Clock className="size-3.5" /> Change to “{instance.pending_plan}” pending payment
            </p>
          )}
          {instance.scheduled_plan && (
            <p className="mt-2 inline-flex items-center gap-1.5 text-xs text-info">
              <Clock className="size-3.5" /> Downgrade to “{instance.scheduled_plan}” scheduled for next billing cycle
            </p>
          )}
        </div>
        <Button
          variant="secondary"
          className="shrink-0"
          onClick={() => {
            window.location.href = `/my/instances/${instance.id}/${instance.is_trial ? "upgrade" : "change-plan"}`;
          }}
        >
          <ArrowUpCircle className="size-4" />
          {instance.is_trial ? "Upgrade plan" : "Change plan"}
        </Button>
      </Card>

      <h2 className="mt-10 text-lg font-semibold">Manage</h2>
      <div className="mt-4 grid gap-4 sm:grid-cols-3">
        {subnav.map((s) => (
          <Link key={s.to} to={s.to}>
            <Card className="group flex items-center gap-4 p-5 transition-all hover:-translate-y-0.5 hover:border-primary/40">
              <span className="flex size-11 items-center justify-center rounded-xl bg-primary/15 text-primary-glow">
                <s.icon className="size-5" />
              </span>
              <div>
                <p className="font-medium">{s.label}</p>
                <p className="text-xs text-muted">{s.label === "Logs" ? "Live stream" : "Manage"}</p>
              </div>
            </Card>
          </Link>
        ))}
      </div>
    </div>
  );
}

function UsageCard({
  icon: Icon,
  label,
  value,
  active,
}: {
  icon: typeof Cpu;
  label: string;
  value: number;
  active: boolean;
}) {
  const tone = value >= 85 ? "bg-danger" : value >= 65 ? "bg-warning" : "bg-primary-glow";
  return (
    <Card className="p-5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-sm text-muted">
          <Icon className="size-4" />
          {label}
        </div>
        <span className="text-sm font-semibold tabular-nums">{active ? `${value}%` : "—"}</span>
      </div>
      <div className="mt-3 h-2 overflow-hidden rounded-full bg-background">
        <div
          className={cn("h-full rounded-full transition-all duration-700 ease-out", active ? tone : "bg-border")}
          style={{ width: active ? `${value}%` : "0%" }}
        />
      </div>
    </Card>
  );
}
