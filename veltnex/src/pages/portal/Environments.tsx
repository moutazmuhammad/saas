import * as React from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  Search,
  GitBranch,
  GitMerge,
  Plus,
  Trash2,
  ExternalLink,
  Rocket,
  FlaskConical,
  Server,
  Link2,
  Copy,
  Check,
  RotateCw,
  Play,
  Square,
  Database,
  Code2,
  ScrollText,
  Archive,
  ArrowRight,
  Terminal,
  GitFork,
  Settings,
  FolderGit2,
  Layers,
  FileCode2,
  Clock,
} from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/input";
import { Dialog } from "@/components/ui/dialog";
import { ActionButton } from "@/components/ActionButton";
import { AlertBanner } from "@/components/AlertBanner";
import { StatusBadge } from "@/components/StatusBadge";
import { Spinner } from "@/components/Spinner";
import { PortalBreadcrumb } from "@/components/layout/PortalLayout";
import { useToast } from "@/context/ToastContext";
import { cn } from "@/lib/utils";
import {
  api,
  ApiError,
  type EnvChild,
  type ProjectEnvironments,
  type StatusData,
} from "@/lib/api";

const TRANSIENT = new Set([
  "pending_payment",
  "paid",
  "pending_provision",
  "provisioning",
]);

const STAGE_ICON = {
  production: Server,
  staging: FlaskConical,
  development: Rocket,
} as const;

function dotClass(state: string) {
  if (state === "running") return "bg-success";
  if (state === "failed") return "bg-danger";
  if (TRANSIENT.has(state)) return "bg-info animate-pulse-soft";
  return "bg-muted";
}

export default function Environments() {
  const { id = "" } = useParams();
  const instanceId = Number(id);
  const navigate = useNavigate();
  const toast = useToast();
  const [searchParams, setSearchParams] = useSearchParams();
  const envParam = Number(searchParams.get("env")) || null;

  const [data, setData] = React.useState<ProjectEnvironments | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [selectedId, setSelectedId] = React.useState<number | null>(envParam);
  const [filter, setFilter] = React.useState("");

  // Select an environment AND reflect it in the URL (?env=) so the workspace
  // is deep-linkable / shareable and the command palette can target it.
  const selectEnv = React.useCallback(
    (envId: number) => {
      setSelectedId(envId);
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.set("env", String(envId));
          return next;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  const [createType, setCreateType] =
    React.useState<"staging" | "development" | null>(null);
  const [deleteTarget, setDeleteTarget] = React.useState<EnvChild | null>(null);
  const [mergePrompt, setMergePrompt] =
    React.useState<{ source: EnvChild; target: EnvChild } | null>(null);
  const [draggingId, setDraggingId] = React.useState<number | null>(null);
  const [dragOverId, setDragOverId] = React.useState<number | null>(null);

  const load = React.useCallback(async () => {
    try {
      const d = await api.environments(instanceId);
      setData(d);
      setSelectedId((cur) => {
        const all = [d.production, ...d.environments];
        if (cur && all.some((e) => e.id === cur)) return cur;
        if (envParam && all.some((e) => e.id === envParam)) return envParam;
        return d.production.id;
      });
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not load this project.");
    }
  }, [instanceId]);

  React.useEffect(() => {
    load();
  }, [load]);

  const hasTransient = !!data?.environments.some((c) => TRANSIENT.has(c.state));
  React.useEffect(() => {
    if (!hasTransient) return;
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [hasTransient, load]);

  const allEnvs = React.useMemo<EnvChild[]>(
    () => (data ? [data.production, ...data.environments] : []),
    [data],
  );
  const selected = allEnvs.find((e) => e.id === selectedId) || data?.production || null;
  const canCreate = !!data?.has_repo;

  const doMerge = (target: EnvChild) => {
    const source = allEnvs.find((e) => e.id === draggingId) || null;
    setDraggingId(null);
    setDragOverId(null);
    if (source && source.id !== target.id) setMergePrompt({ source, target });
  };

  if (error) {
    return (
      <div className="animate-fade-in">
        <PortalBreadcrumb items={[{ label: "Projects", to: "/my/instances" }, { label: "Project" }]} />
        <AlertBanner className="mt-6" variant="danger" title="Project" description={error} />
      </div>
    );
  }
  if (!data || !selected) {
    return (
      <div className="mt-20 flex justify-center">
        <Spinner size="lg" label="Loading project…" />
      </div>
    );
  }

  const staging = data.environments.filter((e) => e.environment === "staging");
  const development = data.environments.filter((e) => e.environment === "development");

  return (
    <div className="animate-fade-in">
      <PortalBreadcrumb
        items={[
          { label: "Projects", to: "/my/instances" },
          { label: data.project_name },
        ]}
      />

      <div className="mt-2 flex flex-col gap-5 lg:flex-row">
        {/* ───────── Left sidebar: branches (sticky per-project bar) ───── */}
        <aside className="lg:sticky lg:top-20 lg:max-h-[calc(100vh-6rem)] lg:w-64 lg:shrink-0 lg:self-start lg:overflow-y-auto">
          <div className="rounded-xl border border-border bg-card/40">
            <div className="border-b border-border p-3">
              <div className="relative">
                <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted" />
                <Input
                  className="h-9 pl-8"
                  placeholder="Filter branches…"
                  value={filter}
                  onChange={(e) => setFilter(e.target.value)}
                />
              </div>
            </div>

            <div className="p-2">
              <div className="px-2 py-1.5">
                <p className="text-[11px] font-semibold uppercase tracking-wide text-muted">Project</p>
                <p className="mt-0.5 truncate text-sm font-semibold">{data.project_name}</p>
                {data.repo_url && (
                  <p className="truncate text-xs text-muted">{repoShort(data.repo_url)}</p>
                )}
              </div>

              <SidebarSection title="Production">
                <BranchItem
                  env={data.production}
                  filter={filter}
                  selected={selectedId === data.production.id}
                  onSelect={() => selectEnv(data.production.id)}
                  drag={dragHandlers(data.production)}
                />
              </SidebarSection>

              <SidebarSection
                title="Staging"
                onAdd={canCreate ? () => setCreateType("staging") : undefined}
                addTitle={canCreate ? undefined : "Connect a repository first"}
              >
                <BranchList
                  envs={staging}
                  filter={filter}
                  selectedId={selectedId}
                  onSelect={selectEnv}
                  dragHandlers={dragHandlers}
                />
              </SidebarSection>

              <SidebarSection
                title="Development"
                onAdd={canCreate ? () => setCreateType("development") : undefined}
                addTitle={canCreate ? undefined : "Connect a repository first"}
              >
                <BranchList
                  envs={development}
                  filter={filter}
                  selectedId={selectedId}
                  onSelect={selectEnv}
                  dragHandlers={dragHandlers}
                />
              </SidebarSection>
            </div>
          </div>
        </aside>

        {/* ───────── Main panel: selected environment ───────── */}
        <div className="min-w-0 flex-1">
          {!canCreate && (
            <Card className="mb-4 flex flex-col gap-3 border-info/40 bg-info/5 p-4 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-start gap-3">
                <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-info/10 text-info">
                  <Link2 className="size-4" />
                </span>
                <div>
                  <p className="text-sm font-medium">Connect a Git repository to add environments</p>
                  <p className="text-xs text-muted">Staging and Development servers run on branches of your repo.</p>
                </div>
              </div>
              <Button className="shrink-0" onClick={() => navigate(`/my/instances/${data.production.id}/code`)}>
                <GitBranch className="size-4" />
                Connect
              </Button>
            </Card>
          )}

          <MainPanel
            key={selected.id}
            env={selected}
            project={data}
            onDelete={selected.is_production ? undefined : () => setDeleteTarget(selected)}
            onMergeInto={() => {
              // Open merge dialog choosing this env as the target.
              const others = allEnvs.filter((e) => e.id !== selected.id);
              if (others.length) setMergePrompt({ source: others[0], target: selected });
            }}
            onChanged={load}
          />

          {canCreate && allEnvs.length > 1 && (
            <p className="mt-3 flex items-center gap-1.5 text-xs text-muted">
              <GitMerge className="size-3.5" />
              Tip: drag a branch onto another in the sidebar to merge it and redeploy.
            </p>
          )}
        </div>
      </div>

      <CreateEnvDialog
        instanceId={instanceId}
        type={createType}
        onClose={() => setCreateType(null)}
        onCreated={(auto, childId) => {
          setCreateType(null);
          if (childId) selectEnv(childId);
          if (auto) toast.success("Environment created", "Provisioning your new server now.");
          load();
        }}
      />
      <DeleteEnvDialog
        instanceId={instanceId}
        env={deleteTarget}
        onClose={() => setDeleteTarget(null)}
        onDeleted={() => {
          setDeleteTarget(null);
          selectEnv(data.production.id);
          toast.success("Environment removed", "The server is being torn down.");
          load();
        }}
      />
      <MergeEnvDialog
        instanceId={instanceId}
        prompt={mergePrompt}
        environments={allEnvs}
        onPick={(p) => setMergePrompt(p)}
        onClose={() => setMergePrompt(null)}
        onMerged={(msg) => {
          setMergePrompt(null);
          toast.success("Merge complete", msg);
          load();
        }}
      />
    </div>
  );

  function dragHandlers(env: EnvChild) {
    return {
      draggable: canCreate,
      isDragging: draggingId === env.id,
      isDropTarget: dragOverId === env.id && draggingId !== null && draggingId !== env.id,
      onDragStart: () => setDraggingId(env.id),
      onDragEnd: () => {
        setDraggingId(null);
        setDragOverId(null);
      },
      onDragOver: (e: React.DragEvent) => {
        if (draggingId !== null && draggingId !== env.id) {
          e.preventDefault();
          setDragOverId(env.id);
        }
      },
      onDragLeave: () => setDragOverId((p) => (p === env.id ? null : p)),
      onDrop: (e: React.DragEvent) => {
        e.preventDefault();
        doMerge(env);
      },
    };
  }
}

function repoShort(url: string) {
  return url.replace(/^https?:\/\//, "").replace(/\.git$/, "");
}

/* ───────────────────────── Sidebar ───────────────────────── */

function SidebarSection({
  title,
  onAdd,
  addTitle,
  children,
}: {
  title: string;
  onAdd?: () => void;
  addTitle?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="mt-2">
      <div className="flex items-center justify-between px-2 py-1">
        <p className="text-[11px] font-semibold uppercase tracking-wide text-muted">{title}</p>
        {(onAdd || addTitle) && (
          <button
            type="button"
            onClick={onAdd}
            disabled={!onAdd}
            title={addTitle}
            className="flex size-5 items-center justify-center rounded text-muted transition-colors hover:bg-border/60 hover:text-foreground disabled:opacity-40"
          >
            <Plus className="size-3.5" />
          </button>
        )}
      </div>
      <div className="flex flex-col gap-0.5">{children}</div>
    </div>
  );
}

function BranchList({
  envs,
  filter,
  selectedId,
  onSelect,
  dragHandlers,
}: {
  envs: EnvChild[];
  filter: string;
  selectedId: number | null;
  onSelect: (id: number) => void;
  dragHandlers: (env: EnvChild) => ReturnType<typeof noopHandlers>;
}) {
  const shown = envs.filter(
    (e) =>
      !filter ||
      e.name.toLowerCase().includes(filter.toLowerCase()) ||
      e.branch.toLowerCase().includes(filter.toLowerCase()),
  );
  if (shown.length === 0) {
    return <p className="px-2 py-1.5 text-xs text-muted/70">No branches</p>;
  }
  return (
    <>
      {shown.map((env) => (
        <BranchItem
          key={env.id}
          env={env}
          filter={filter}
          selected={selectedId === env.id}
          onSelect={() => onSelect(env.id)}
          drag={dragHandlers(env)}
        />
      ))}
    </>
  );
}

function noopHandlers() {
  return {
    draggable: false,
    isDragging: false,
    isDropTarget: false,
    onDragStart: () => {},
    onDragEnd: () => {},
    onDragOver: (_e: React.DragEvent) => {},
    onDragLeave: () => {},
    onDrop: (_e: React.DragEvent) => {},
  };
}

function BranchItem({
  env,
  filter,
  selected,
  onSelect,
  drag,
}: {
  env: EnvChild;
  filter: string;
  selected: boolean;
  onSelect: () => void;
  drag: ReturnType<typeof noopHandlers>;
}) {
  const matches =
    !filter ||
    env.name.toLowerCase().includes(filter.toLowerCase()) ||
    env.branch.toLowerCase().includes(filter.toLowerCase());
  if (!matches) return null;
  return (
    <button
      type="button"
      onClick={onSelect}
      draggable={drag.draggable}
      onDragStart={drag.onDragStart}
      onDragEnd={drag.onDragEnd}
      onDragOver={drag.onDragOver}
      onDragLeave={drag.onDragLeave}
      onDrop={drag.onDrop}
      className={cn(
        "flex w-full items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors",
        selected ? "bg-primary/10 text-foreground" : "text-muted hover:bg-border/40 hover:text-foreground",
        drag.draggable && "cursor-grab active:cursor-grabbing",
        drag.isDragging && "opacity-40",
        drag.isDropTarget && "ring-2 ring-primary/40",
      )}
      title={env.branch}
    >
      <span className="flex min-w-0 items-center gap-2">
        <GitBranch className="size-3.5 shrink-0 text-muted" />
        <span className="truncate">{env.name}</span>
      </span>
      <span className="flex shrink-0 items-center gap-2">
        {env.version && <span className="text-[11px] text-muted/80">{env.version}</span>}
        <span className={cn("size-2 rounded-full", dotClass(env.state))} />
      </span>
    </button>
  );
}

/* ───────────────────────── Main panel ───────────────────────── */

function MainPanel({
  env,
  project,
  onDelete,
  onMergeInto,
  onChanged,
}: {
  env: EnvChild;
  project: ProjectEnvironments;
  onDelete?: () => void;
  onMergeInto: () => void;
  onChanged: () => void;
}) {
  const navigate = useNavigate();
  const toast = useToast();
  const [status, setStatus] = React.useState<StatusData | null>(null);
  const [pending, setPending] = React.useState<string | null>(null);
  const [copied, setCopied] = React.useState(false);

  const refreshStatus = React.useCallback(async () => {
    try {
      setStatus(await api.instanceStatus(env.id));
    } catch {
      /* ignore */
    }
  }, [env.id]);

  React.useEffect(() => {
    setStatus(null);
    refreshStatus();
  }, [refreshStatus]);

  const liveState = status?.state || env.state;
  const transient = TRANSIENT.has(liveState);
  React.useEffect(() => {
    if (!transient) return;
    const t = setInterval(refreshStatus, 4000);
    return () => clearInterval(t);
  }, [transient, refreshStatus]);

  const run = async (action: string, ok: string) => {
    setPending(action);
    try {
      await api.instanceAction(env.id, action);
      toast.success(ok);
      await refreshStatus();
      onChanged();
    } catch (e) {
      toast.error("Action failed", e instanceof ApiError ? e.message : "Please try again.");
    } finally {
      setPending(null);
    }
  };

  const cloneCmd = project.repo_url
    ? `git clone --branch ${env.branch} ${project.repo_url}`
    : "";
  const url = status?.url || env.url;
  const isRunning = liveState === "running";
  const isStopped = liveState === "stopped";
  const pendingPay = env.pending_payment && env.pending_invoice_id;

  // Top toolbar strip (Odoo.sh: Clone / Shell / SQL / Logs / Fork / Merge /
  // Submodule). We light up what the platform supports and disable the rest
  // with an honest "needs backend agent" hint rather than faking them.
  const [tool, setTool] = React.useState("clone");
  const toolStrip: {
    key: string;
    label: string;
    icon: React.ComponentType<{ className?: string }>;
    enabled: boolean;
    action?: () => void;
    soon?: string;
  }[] = [
    { key: "clone", label: "Clone", icon: Copy, enabled: true, action: () => setTool("clone") },
    { key: "shell", label: "Shell", icon: Terminal, enabled: false, soon: "In-browser shell needs a backend agent" },
    { key: "sql", label: "SQL", icon: FileCode2, enabled: false, soon: "Web SQL console needs a backend agent" },
    { key: "logs", label: "Logs", icon: ScrollText, enabled: true, action: () => navigate(`/my/instances/${env.id}/logs`) },
    { key: "fork", label: "Fork", icon: GitFork, enabled: false, soon: "Fork is coming soon" },
    { key: "merge", label: "Merge", icon: GitMerge, enabled: true, action: onMergeInto },
    { key: "submodule", label: "Submodule", icon: Layers, enabled: false, soon: "Submodules are coming soon" },
  ];

  const subtabs: { label: string; icon: React.ComponentType<{ className?: string }>; to?: string }[] = [
    { label: "Overview", icon: Clock },
    { label: "Databases", icon: Database, to: `/my/instances/${env.id}/databases` },
    { label: "Code", icon: Code2, to: `/my/instances/${env.id}/code` },
    { label: "Logs", icon: ScrollText, to: `/my/instances/${env.id}/logs` },
    { label: "Backups", icon: Archive, to: `/my/instances/${env.id}/backups` },
    { label: "Settings", icon: Settings, to: `/my/instances/${env.id}` },
  ];

  return (
    <Card className="overflow-hidden">
      {/* Header */}
      <div className="flex flex-col gap-4 border-b border-border p-5 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2.5">
            <h1 className="text-xl font-bold tracking-tight">{env.name}</h1>
            <StatusBadge status={liveState} />
            <span className="rounded-full border border-border px-2 py-0.5 text-xs text-muted">
              {env.environment_label}
            </span>
            {env.version && <span className="text-xs text-muted">Odoo {env.version}</span>}
          </div>
          <p className="mt-1.5 flex items-center gap-1.5 font-mono text-xs text-muted">
            <GitBranch className="size-3" />
            {env.branch}
            {url && (
              <>
                <span className="text-border">·</span>
                <a href={url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 hover:text-primary">
                  {env.domain}
                  <ExternalLink className="size-3" />
                </a>
              </>
            )}
          </p>
        </div>

        {/* Toolbar strip */}
        <div className="flex flex-wrap gap-1 rounded-lg border border-border bg-card/60 p-1">
          {toolStrip.map((t) => (
            <button
              key={t.key}
              type="button"
              disabled={!t.enabled}
              title={t.soon}
              onClick={t.action}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
                t.key === "clone" && tool === "clone"
                  ? "bg-primary/15 text-foreground"
                  : t.enabled
                    ? "text-muted hover:bg-border/50 hover:text-foreground"
                    : "cursor-not-allowed text-muted/40",
              )}
            >
              <t.icon className="size-3.5" />
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {/* Clone command bar (when Clone tool is active) */}
      {tool === "clone" && cloneCmd && (
        <div className="flex items-center gap-2 border-b border-border bg-background/40 px-5 py-2.5">
          <button
            type="button"
            onClick={() => {
              navigator.clipboard?.writeText(cloneCmd);
              setCopied(true);
              setTimeout(() => setCopied(false), 1500);
            }}
            className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-border px-2.5 py-1 text-xs font-medium text-muted transition-colors hover:text-foreground"
          >
            {copied ? <Check className="size-3.5 text-success" /> : <Copy className="size-3.5" />}
            {copied ? "Copied" : "Copy"}
          </button>
          <code className="min-w-0 flex-1 truncate font-mono text-xs text-muted">{cloneCmd}</code>
        </div>
      )}

      {/* Sub-tab bar */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-3 py-2">
        <div className="flex flex-wrap">
          {subtabs.map((t) => {
            const active = t.label === "Overview";
            return (
              <button
                key={t.label}
                onClick={() => t.to && navigate(t.to)}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm transition-colors",
                  active
                    ? "bg-primary/10 font-medium text-foreground"
                    : "text-muted hover:bg-border/50 hover:text-foreground",
                )}
              >
                <t.icon className="size-4" />
                {t.label}
              </button>
            );
          })}
        </div>
        <div className="flex items-center gap-2 pr-2">
          {url && (
            <Button size="sm" onClick={() => window.open(url, "_blank")}>
              <ExternalLink className="size-4" />
              Open app
            </Button>
          )}
          {onDelete && (
            <Button size="sm" variant="danger" onClick={onDelete}>
              <Trash2 className="size-4" />
              Delete
            </Button>
          )}
        </div>
      </div>

      {/* Body */}
      <div className="p-5">
        {pendingPay ? (
          <AlertBanner
            variant="warning"
            title="Payment pending"
            description="Finish checkout to provision this server."
            action={
              <Button size="sm" onClick={() => (window.location.href = `/my/instances/${env.id}/checkout`)}>
                Complete checkout
              </Button>
            }
          />
        ) : (
          <>
            {/* Action row */}
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex flex-wrap gap-2">
                {isRunning && (
                  <ActionButton
                    icon={RotateCw}
                    loading={pending === "restart"}
                    loadingText="Re-deploying…"
                    disabled={!!pending}
                    onClick={() => run("restart", "Re-deploying")}
                  >
                    Re-deploy
                  </ActionButton>
                )}
                {isRunning && (
                  <ActionButton
                    variant="secondary"
                    icon={Square}
                    loading={pending === "stop"}
                    loadingText="Stopping…"
                    disabled={!!pending}
                    onClick={() => run("stop", "Stopping")}
                  >
                    Stop
                  </ActionButton>
                )}
                {isStopped && (
                  <ActionButton
                    icon={Play}
                    loading={pending === "start"}
                    loadingText="Starting…"
                    disabled={!!pending}
                    onClick={() => run("start", "Starting")}
                  >
                    Start
                  </ActionButton>
                )}
              </div>
              {project.repo_url && (
                <Button variant="secondary" onClick={() => window.open(repoWeb(project.repo_url), "_blank")}>
                  <FolderGit2 className="size-4" />
                  Open repository
                </Button>
              )}
            </div>

            {/* Metrics */}
            {status?.usage && isRunning && (
              <div className="mt-4 grid grid-cols-3 gap-3">
                <Metric label="CPU" value={`${status.usage.cpu}%`} />
                <Metric label="RAM" value={`${status.usage.ram}%`} />
                <Metric label="Disk" value={`${status.usage.storage}%`} />
              </div>
            )}

            {/* Current deployment */}
            <div className="mt-6">
              <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-muted">Deployment</p>
              <div className="rounded-lg border border-border p-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-sm font-medium">Current deployment</span>
                  <StatusBadge status={liveState} />
                </div>
                <div className="mt-2 flex items-center gap-1.5 font-mono text-xs text-muted">
                  <GitBranch className="size-3" />
                  {env.branch}
                </div>
                {status?.provisioning_log && (
                  <pre className="mt-3 max-h-72 overflow-auto rounded-md border border-border bg-background/60 p-3 font-mono text-[11px] leading-relaxed text-muted">
                    {status.provisioning_log.trimEnd()}
                  </pre>
                )}
              </div>
            </div>
          </>
        )}
      </div>
    </Card>
  );
}

function repoWeb(url: string) {
  // Turn a clone URL into a browsable web URL (strip .git / git@ form).
  let u = url.trim();
  if (u.startsWith("git@")) {
    const [, path] = u.split(":");
    u = "https://" + u.slice(4).split(":")[0] + "/" + (path || "");
  }
  return u.replace(/\.git$/, "");
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border bg-card/40 p-3 text-center">
      <p className="text-lg font-semibold">{value}</p>
      <p className="text-xs text-muted">{label}</p>
    </div>
  );
}

/* ───────────────────────── Dialogs ───────────────────────── */

function MergeEnvDialog({
  instanceId,
  prompt,
  environments,
  onPick,
  onClose,
  onMerged,
}: {
  instanceId: number;
  prompt: { source: EnvChild; target: EnvChild } | null;
  environments: EnvChild[];
  onPick: (p: { source: EnvChild; target: EnvChild }) => void;
  onClose: () => void;
  onMerged: (message: string) => void;
}) {
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (prompt) {
      setLoading(false);
      setError(null);
    }
  }, [prompt]);

  const submit = async () => {
    if (!prompt) return;
    setError(null);
    setLoading(true);
    try {
      const res = await api.environmentMerge(instanceId, prompt.source.id, prompt.target.id);
      const msg =
        res.status === "up_to_date"
          ? `${prompt.target.name} is already up to date with ${prompt.source.branch}.`
          : `Merged ${res.source_branch} into ${res.target_branch}.${res.redeployed ? " Redeploying…" : ""}`;
      onMerged(msg);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't merge.");
      setLoading(false);
    }
  };

  const sources = prompt ? environments.filter((e) => e.id !== prompt.target.id) : [];
  const toProd = prompt?.target.is_production;

  return (
    <Dialog open={!!prompt} onClose={onClose} title="Merge branches">
      {error && <AlertBanner className="mb-4" variant="danger" title="Couldn't merge" description={error} />}
      {prompt && (
        <>
          <div className="flex items-center justify-center gap-3 rounded-lg border border-border bg-card/50 p-4">
            <BranchPill name={prompt.source.name} branch={prompt.source.branch} />
            <ArrowRight className="size-5 shrink-0 text-muted" />
            <BranchPill name={prompt.target.name} branch={prompt.target.branch} highlight />
          </div>

          <div className="mt-4 space-y-2">
            <Label htmlFor="merge-source">Merge from</Label>
            <select
              id="merge-source"
              className="h-10 w-full rounded-lg border border-border bg-card px-3 text-sm"
              value={prompt.source.id}
              onChange={(e) => {
                const src = sources.find((s) => s.id === Number(e.target.value));
                if (src) onPick({ source: src, target: prompt.target });
              }}
            >
              {sources.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name} ({s.branch})
                </option>
              ))}
            </select>
          </div>

          <p className="mt-3 text-sm text-muted">
            Merges{" "}
            <code className="rounded bg-border/60 px-1 py-0.5 font-mono text-xs text-foreground">{prompt.source.branch}</code>{" "}
            into{" "}
            <code className="rounded bg-border/60 px-1 py-0.5 font-mono text-xs text-foreground">{prompt.target.branch}</code>{" "}
            and redeploys <strong>{prompt.target.name}</strong>.
          </p>
          {toProd && (
            <AlertBanner
              className="mt-4"
              variant="warning"
              title="This targets Production"
              description="The merged code deploys to your live Production server."
            />
          )}
        </>
      )}
      <div className="mt-6 flex justify-end gap-2">
        <Button variant="secondary" onClick={onClose} disabled={loading}>
          Cancel
        </Button>
        <ActionButton loading={loading} loadingText="Merging…" onClick={submit}>
          <GitMerge className="size-4" />
          Merge &amp; redeploy
        </ActionButton>
      </div>
    </Dialog>
  );
}

function BranchPill({ name, branch, highlight }: { name: string; branch: string; highlight?: boolean }) {
  return (
    <div
      className={cn(
        "min-w-0 rounded-lg border px-3 py-2 text-center",
        highlight ? "border-primary-glow/40 bg-primary-glow/5" : "border-border",
      )}
    >
      <p className="truncate text-sm font-medium">{name}</p>
      <p className="mt-0.5 flex items-center justify-center gap-1 truncate text-xs text-muted">
        <GitBranch className="size-3" />
        {branch}
      </p>
    </div>
  );
}

function CreateEnvDialog({
  instanceId,
  type,
  onClose,
  onCreated,
}: {
  instanceId: number;
  type: "staging" | "development" | null;
  onClose: () => void;
  onCreated: (autoProvisioned: boolean, childId?: number) => void;
}) {
  const [name, setName] = React.useState("");
  const [branch, setBranch] = React.useState("");
  const [branches, setBranches] = React.useState<string[]>([]);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const isStaging = type === "staging";

  React.useEffect(() => {
    if (!type) return;
    setName("");
    setBranch("");
    setError(null);
    setLoading(false);
    if (type === "staging") {
      api.instanceBranches(instanceId).then((b) => setBranches(b.branches)).catch(() => setBranches([]));
    }
  }, [type, instanceId]);

  const ok = name.trim().length > 0;

  const submit = async () => {
    if (!type || !ok) return;
    setError(null);
    setLoading(true);
    try {
      const res = await api.environmentCreate(
        instanceId,
        type,
        name.trim(),
        isStaging ? branch.trim() || undefined : undefined,
      );
      if (!res.auto_provisioned && res.checkout_url) {
        window.location.href = res.checkout_url;
        return;
      }
      onCreated(!!res.auto_provisioned, res.child_id);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't create the environment.");
      setLoading(false);
    }
  };

  return (
    <Dialog open={!!type} onClose={onClose} title={isStaging ? "New staging server" : "New development server"}>
      {error && <AlertBanner className="mb-4" variant="danger" title="Couldn't create" description={error} />}
      <div className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="env-name">{isStaging ? "Server name" : "Server / branch name"}</Label>
          <Input
            id="env-name"
            autoFocus
            autoComplete="off"
            placeholder={isStaging ? "staging" : "feature-x"}
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && ok && submit()}
          />
          <p className="text-xs text-muted">
            {isStaging
              ? "A new server is provisioned automatically."
              : "A Git branch with this name is created (from the main branch) and linked to the server."}
          </p>
        </div>
        {isStaging && (
          <div className="space-y-2">
            <Label htmlFor="env-branch">Git branch (optional)</Label>
            <select
              id="env-branch"
              className="h-10 w-full rounded-lg border border-border bg-card px-3 text-sm"
              value={branch}
              onChange={(e) => setBranch(e.target.value)}
            >
              <option value="">New branch from main</option>
              {branches.map((b) => (
                <option key={b} value={b}>
                  {b}
                </option>
              ))}
            </select>
          </div>
        )}
      </div>
      <div className="mt-6 flex justify-end gap-2">
        <Button variant="secondary" onClick={onClose} disabled={loading}>
          Cancel
        </Button>
        <ActionButton loading={loading} loadingText="Creating…" disabled={!ok} onClick={submit}>
          Create server
        </ActionButton>
      </div>
    </Dialog>
  );
}

function DeleteEnvDialog({
  instanceId,
  env,
  onClose,
  onDeleted,
}: {
  instanceId: number;
  env: EnvChild | null;
  onClose: () => void;
  onDeleted: () => void;
}) {
  const [deleteBranch, setDeleteBranch] = React.useState(false);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (env) {
      setDeleteBranch(false);
      setLoading(false);
      setError(null);
    }
  }, [env]);

  const submit = async () => {
    if (!env) return;
    setError(null);
    setLoading(true);
    try {
      await api.environmentDelete(instanceId, env.id, deleteBranch);
      onDeleted();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't remove the environment.");
      setLoading(false);
    }
  };

  return (
    <Dialog open={!!env} onClose={onClose} title="Remove environment">
      {error && <AlertBanner className="mb-4" variant="danger" title="Couldn't remove" description={error} />}
      <div className="flex gap-3">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-danger/10 text-danger">
          <Trash2 className="size-5" />
        </span>
        <div className="text-sm">
          <p className="font-medium text-foreground">
            Remove the {env?.environment_label.toLowerCase()} server <strong>{env?.name}</strong>?
          </p>
          <p className="mt-1 text-muted">
            The server and its data are deleted. Any unused time on your current cycle is credited back to your
            wallet. This can't be undone.
          </p>
        </div>
      </div>
      <label className="mt-5 flex items-start gap-2.5 rounded-lg border border-border p-3 text-sm">
        <input type="checkbox" className="mt-0.5" checked={deleteBranch} onChange={(e) => setDeleteBranch(e.target.checked)} />
        <span>
          Also delete the Git branch{" "}
          <code className="rounded bg-border/60 px-1 py-0.5 font-mono text-xs text-foreground">{env?.branch}</code> on the
          remote. Leave unchecked to keep your branch.
        </span>
      </label>
      <div className="mt-6 flex justify-end gap-2">
        <Button variant="secondary" onClick={onClose} disabled={loading}>
          Cancel
        </Button>
        <ActionButton variant="danger" loading={loading} loadingText="Removing…" onClick={submit}>
          Remove server
        </ActionButton>
      </div>
    </Dialog>
  );
}
