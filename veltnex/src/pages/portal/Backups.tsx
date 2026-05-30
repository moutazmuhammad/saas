import * as React from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Archive, Plus, Download, Clock, ShieldCheck, HardDriveDownload } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ActionButton } from "@/components/ActionButton";
import { AlertBanner } from "@/components/AlertBanner";
import { StatusBadge } from "@/components/StatusBadge";
import { EmptyState } from "@/components/EmptyState";
import { InfoCard } from "@/components/InfoCard";
import { Spinner } from "@/components/Spinner";
import { PortalBreadcrumb } from "@/components/layout/PortalLayout";
import { useToast } from "@/context/ToastContext";
import { api, ApiError, type ApiBackup } from "@/lib/api";
import { formatDateTime, formatSizeMb } from "@/lib/format";

export default function Backups() {
  const { id = "" } = useParams();
  const instanceId = Number(id);
  const navigate = useNavigate();
  const toast = useToast();

  const [backups, setBackups] = React.useState<ApiBackup[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [creating, setCreating] = React.useState(false);

  const load = React.useCallback(async () => {
    try {
      setBackups(await api.backups(instanceId));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not load backups.");
    }
  }, [instanceId]);

  React.useEffect(() => {
    load();
  }, [load]);

  // Poll while a backup is in progress.
  const hasRunning = !!backups?.some((b) => b.status === "in_progress");
  React.useEffect(() => {
    if (!hasRunning) return;
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [hasRunning, load]);

  const createBackup = async () => {
    setCreating(true);
    try {
      await api.backupCreate(instanceId);
      toast.success("Backup started", "Your on-demand backup is being created.");
      load();
    } catch (e) {
      toast.error("Couldn't start backup", e instanceof ApiError ? e.message : "Please try again.");
    } finally {
      setCreating(false);
    }
  };

  const lastDone = backups?.find((b) => b.status === "available");
  const totalGb = ((backups?.reduce((a, b) => a + b.size_mb, 0) || 0) / 1024).toFixed(1);

  return (
    <div className="animate-fade-in">
      <PortalBreadcrumb
        items={[
          { label: "Instances", to: "/my/instances" },
          { label: "Instance", to: `/my/instances/${id}` },
          { label: "Backups" },
        ]}
      />

      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Backups</h1>
          <p className="mt-1 text-sm text-muted">Automatic snapshots plus on-demand backups.</p>
        </div>
        <ActionButton icon={Plus} loading={creating} loadingText="Starting…" onClick={createBackup} disabled={!backups}>
          Create backup
        </ActionButton>
      </div>

      {error && <AlertBanner className="mt-6" variant="danger" title="Backups" description={error} />}

      {!backups && !error ? (
        <div className="mt-20 flex justify-center">
          <Spinner size="lg" label="Loading backups…" />
        </div>
      ) : backups ? (
        <>
          <div className="mt-6 grid gap-4 sm:grid-cols-3">
            <InfoCard label="Total backups" value={backups.length} icon={Archive} />
            <InfoCard label="Storage used" value={`${totalGb} GB`} icon={HardDriveDownload} />
            <InfoCard
              label="Latest"
              value={<span className="text-base">{lastDone ? formatDateTime(lastDone.created).split(",")[0] : "—"}</span>}
              icon={ShieldCheck}
            />
          </div>

          {backups.length === 0 ? (
            <EmptyState
              className="mt-8"
              icon={Archive}
              title="No backups yet"
              description="Create an on-demand backup, or wait for the next automatic snapshot."
              action={<Button onClick={createBackup}>Create backup</Button>}
            />
          ) : (
            <Card className="mt-6 divide-y divide-border">
              {backups.map((b) => (
                <div key={b.id} className="flex flex-col gap-3 p-5 sm:flex-row sm:items-center sm:justify-between">
                  <div className="flex items-start gap-3">
                    <span className="flex size-10 shrink-0 items-center justify-center rounded-lg border border-border bg-card text-muted">
                      <Archive className="size-4" />
                    </span>
                    <div>
                      <div className="flex items-center gap-2">
                        <p className="font-medium">{b.label}</p>
                        <span className="rounded-full border border-border px-2 py-0.5 text-[11px] capitalize text-muted">{b.type}</span>
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
