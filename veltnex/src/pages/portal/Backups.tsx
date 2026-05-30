import * as React from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Archive, Download, Clock, ShieldCheck, HardDriveDownload } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { AlertBanner } from "@/components/AlertBanner";
import { StatusBadge } from "@/components/StatusBadge";
import { EmptyState } from "@/components/EmptyState";
import { InfoCard } from "@/components/InfoCard";
import { Spinner } from "@/components/Spinner";
import { PortalBreadcrumb } from "@/components/layout/PortalLayout";
import { api, ApiError, type ApiBackup } from "@/lib/api";
import { formatDateTime, formatSizeMb } from "@/lib/format";

export default function Backups() {
  const { id = "" } = useParams();
  const instanceId = Number(id);
  const navigate = useNavigate();
  const [backups, setBackups] = React.useState<ApiBackup[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  const load = React.useCallback(async () => {
    try {
      setBackups(await api.backups(instanceId));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not load snapshots.");
    }
  }, [instanceId]);

  React.useEffect(() => {
    load();
  }, [load]);

  // This page is for FULL-INSTANCE snapshots only. On-demand,
  // per-database backups live on the Databases page.
  const snapshots = backups ? backups.filter((b) => b.is_full_instance) : null;

  // Poll while a snapshot is in progress.
  const hasRunning = !!snapshots?.some((b) => b.status === "in_progress");
  React.useEffect(() => {
    if (!hasRunning) return;
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [hasRunning, load]);

  const lastDone = snapshots?.find((b) => b.status === "available");
  const totalGb = (((snapshots?.reduce((a, b) => a + b.size_mb, 0)) || 0) / 1024).toFixed(1);

  return (
    <div className="animate-fade-in">
      <PortalBreadcrumb
        items={[
          { label: "Instances", to: "/my/instances" },
          { label: "Instance", to: `/my/instances/${id}` },
          { label: "Snapshots" },
        ]}
      />

      <div>
        <h1 className="text-2xl font-bold tracking-tight">Snapshots</h1>
        <p className="mt-1 text-sm text-muted">
          Automatic daily full-instance snapshots. On-demand, per-database backups are on the Databases page.
        </p>
      </div>

      {error && <AlertBanner className="mt-6" variant="danger" title="Snapshots" description={error} />}

      {!backups && !error ? (
        <div className="mt-20 flex justify-center">
          <Spinner size="lg" label="Loading snapshots…" />
        </div>
      ) : snapshots ? (
        <>
          <div className="mt-6 grid gap-4 sm:grid-cols-3">
            <InfoCard label="Snapshots" value={snapshots.length} icon={Archive} />
            <InfoCard label="Storage used" value={`${totalGb} GB`} icon={HardDriveDownload} />
            <InfoCard
              label="Latest"
              value={<span className="text-base">{lastDone ? formatDateTime(lastDone.created).split(",")[0] : "—"}</span>}
              icon={ShieldCheck}
            />
          </div>

          {snapshots.length === 0 ? (
            <EmptyState
              className="mt-8"
              icon={Archive}
              title="No snapshots yet"
              description="Full-instance snapshots run automatically every day; the first one will appear here once it completes."
            />
          ) : (
            <Card className="mt-6 divide-y divide-border">
              {snapshots.map((b) => (
                <div key={b.id} className="flex flex-col gap-3 p-5 sm:flex-row sm:items-center sm:justify-between">
                  <div className="flex items-start gap-3">
                    <span className="flex size-10 shrink-0 items-center justify-center rounded-lg border border-border bg-card text-muted">
                      <Archive className="size-4" />
                    </span>
                    <div>
                      <div className="flex items-center gap-2">
                        <p className="font-medium">Full snapshot</p>
                        <span className="rounded-full border border-border px-2 py-0.5 text-[11px] text-muted">Automatic</span>
                      </div>
                      <p className="mt-0.5 flex items-center gap-1.5 text-xs text-muted">
                        <Clock className="size-3" />
                        {formatDateTime(b.created)}
                        {b.status === "available" && b.size_mb > 0 && ` · ${formatSizeMb(b.size_mb)}`}
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 sm:justify-end">
                    <StatusBadge status={b.status} />
                    {b.download_url ? (
                      <a href={b.download_url} target="_blank" rel="noreferrer">
                        <Button size="sm" variant="ghost" disabled={b.status !== "available"}>
                          <Download className="size-4" />
                          <span className="hidden sm:inline">Download</span>
                        </Button>
                      </a>
                    ) : (
                      <Button size="sm" variant="ghost" disabled>
                        <Download className="size-4" />
                        <span className="hidden sm:inline">Download</span>
                      </Button>
                    )}
                  </div>
                </div>
              ))}
            </Card>
          )}
        </>
      ) : null}
    </div>
  );
}
