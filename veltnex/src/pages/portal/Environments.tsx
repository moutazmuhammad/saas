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
  ScrollText,
  ArrowRight,
  Terminal,
  FolderGit2,
  FileCode2,
  Github,
  LayoutDashboard,
  Activity,
  Database,
  TerminalSquare,
  TableProperties,
  Archive,
} from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { DeploymentHistory } from "@/components/DeploymentHistory";
import { Input, Label } from "@/components/ui/input";
import { Dialog } from "@/components/ui/dialog";
import { ActionButton } from "@/components/ActionButton";
import { AlertBanner } from "@/components/AlertBanner";
import { StatusBadge } from "@/components/StatusBadge";
import { Spinner } from "@/components/Spinner";
import { useToast } from "@/context/ToastContext";
import { cn } from "@/lib/utils";
import {
  api,
  ApiError,
  type EnvChild,
  type ProjectEnvironments,
  type StatusData,
} from "@/lib/api";
import Code from "@/pages/portal/Code";
import Metrics from "@/pages/portal/Metrics";
import Databases from "@/pages/portal/Databases";
import Logs from "@/pages/portal/Logs";
import Backups from "@/pages/portal/Backups";
import ShellPage from "@/pages/portal/ShellPage";
import SqlPage from "@/pages/portal/SqlPage";

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

// In-page section tabs: every tool for the selected environment swaps in place
// inside the workspace (no navigation away from the Environments page).
// "Code & packages" (key "code") is intentionally NOT in the visible tab bar —
// it's project-wide and reached via the sidebar "Project settings" button (the
// same Code panel), so a duplicate tab would be redundant. It's still a valid
// tab value so that button and any ?tab=code deep-link keep working.
type SectionTab =
  | "overview"
  | "metrics"
  | "databases"
  | "code"
  | "shell"
  | "sql"
  | "logs"
  | "snapshots";
const SECTION_TABS: { key: SectionTab; label: string; icon: typeof Activity }[] = [
  { key: "overview", label: "Overview", icon: LayoutDashboard },
  { key: "metrics", label: "Metrics", icon: Activity },
  { key: "databases", label: "Databases", icon: Database },
  { key: "shell", label: "Shell", icon: TerminalSquare },
  { key: "sql", label: "SQL", icon: TableProperties },
  { key: "logs", label: "Logs", icon: ScrollText },
  { key: "snapshots", label: "Snapshots", icon: Archive },
];
const SECTION_KEYS: readonly string[] = [
  "overview",
  "metrics",
  "databases",
  "code",
  "shell",
  "sql",
  "logs",
  "snapshots",
];
function asTab(v: string | null): SectionTab {
  return v && SECTION_KEYS.includes(v) ? (v as SectionTab) : "overview";
}

function SectionTabBar({
  tab,
  setTab,
}: {
  tab: SectionTab;
  setTab: (t: SectionTab) => void;
}) {
  return (
    <div className="flex shrink-0 gap-1 overflow-x-auto border-b border-border px-3">
      {SECTION_TABS.map((t) => {
        const active = tab === t.key;
        return (
          <button
            key={t.key}
            type="button"
            onClick={() => setTab(t.key)}
            className={cn(
              "flex shrink-0 items-center gap-1.5 border-b-2 px-3 py-2.5 text-sm transition-colors",
              active
                ? "border-primary font-medium text-primary"
                : "border-transparent text-muted hover:text-foreground",
            )}
          >
            <t.icon className="size-4" />
            {t.label}
          </button>
        );
      })}
    </div>
  );
}

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
  // Active in-page section (Overview / Metrics / … ) — the source of truth is
  // the ?tab= URL param so the rail, command palette and deep-links all land on
  // the right section without a page navigation.
  const tab = asTab(searchParams.get("tab"));
  const setTab = React.useCallback(
    (t: SectionTab) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (t === "overview") next.delete("tab");
          else next.set("tab", t);
          return next;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

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
      <div className="flex flex-col gap-5 lg:flex-row">
        {/* ───────── Left sidebar: branches (sticky per-project bar) ───── */}
        <aside className="lg:sticky lg:top-20 lg:max-h-[calc(100dvh-14.5rem)] lg:w-64 lg:shrink-0 lg:self-start lg:overflow-y-auto">
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
              {/* Project settings (Code/repo + packages) lives in the left rail
                  now — reached via ?tab=code, so it's not duplicated here. */}
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
              <Button className="shrink-0" onClick={() => setTab("code")}>
                <GitBranch className="size-4" />
                Connect
              </Button>
            </Card>
          )}

          <MainPanel
            key={selected.id}
            env={selected}
            project={data}
            tab={tab}
            setTab={setTab}
            onDelete={selected.is_production ? undefined : () => setDeleteTarget(selected)}
            onMergeInto={() => {
              // Open merge dialog choosing this env as the target.
              const others = allEnvs.filter((e) => e.id !== selected.id);
              if (others.length) setMergePrompt({ source: others[0], target: selected });
            }}
            onChanged={load}
          />

          {tab === "overview" && canCreate && allEnvs.length > 1 && (
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

// "owner/repo" pulled from any clone-URL form (https or git@).
function repoName(url: string) {
  const m = repoWeb(url).match(/[^/]+\/[^/]+$/);
  return m ? m[0] : repoShort(url);
}

/* ─────────────────── Repository card (Odoo.sh-style) ─────────────────── */
// The connected GitHub repo: its name (linked), the branch, a one-click
// `git clone` with copy, and a button straight to the repo.
function RepoCard({
  repoUrl,
  branch,
  cloneCmd,
}: {
  repoUrl: string;
  branch: string;
  cloneCmd: string;
}) {
  const [copied, setCopied] = React.useState(false);
  const web = repoWeb(repoUrl);
  const copy = () => {
    navigator.clipboard?.writeText(cloneCmd);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  return (
    <div className="mb-5 rounded-xl border border-border bg-card/40 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-foreground/[0.06] text-foreground">
            <Github className="size-5" />
          </span>
          <div className="min-w-0">
            <a
              href={web}
              target="_blank"
              rel="noreferrer"
              className="block truncate font-semibold hover:text-primary"
            >
              {repoName(repoUrl)}
            </a>
            <p className="flex items-center gap-1.5 font-mono text-xs text-muted">
              <GitBranch className="size-3" />
              {branch}
            </p>
          </div>
        </div>
        <Button variant="secondary" size="sm" onClick={() => window.open(web, "_blank", "noopener,noreferrer")}>
          <FolderGit2 className="size-4" />
          Open repository
        </Button>
      </div>

      {/* git clone command + copy */}
      <div className="mt-3 flex items-center gap-2 rounded-lg border border-border bg-background/60 px-3 py-2">
        <code className="min-w-0 flex-1 truncate font-mono text-xs text-muted">{cloneCmd}</code>
        <button
          type="button"
          onClick={copy}
          title="Copy clone command"
          className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-border px-2.5 py-1 text-xs font-medium text-muted transition-colors hover:text-foreground"
        >
          {copied ? <Check className="size-3.5 text-success" /> : <Copy className="size-3.5" />}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
    </div>
  );
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
  tab,
  setTab,
  onDelete,
  onMergeInto,
  onChanged,
}: {
  env: EnvChild;
  project: ProjectEnvironments;
  tab: SectionTab;
  setTab: (t: SectionTab) => void;
  onDelete?: () => void;
  onMergeInto: () => void;
  onChanged: () => void;
}) {
  const navigate = useNavigate();
  const toast = useToast();
  const [status, setStatus] = React.useState<StatusData | null>(null);
  const [pending, setPending] = React.useState<string | null>(null);

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

  const url = status?.url || env.url;
  const isRunning = liveState === "running";
  const isStopped = liveState === "stopped";
  const pendingPay = env.pending_payment && env.pending_invoice_id;
  const cloneCmd = project.repo_url
    ? `git clone --branch ${env.branch} ${project.repo_url}`
    : "";

  // Console sections (Logs/Shell/SQL) need a viewport-bounded panel with their
  // OWN internal scroll so the tail stays on screen. Content sections (Overview/
  // Metrics/Databases/Snapshots) flow naturally and let the PAGE scroll — so the
  // content is never clipped under the section tabs.
  const bounded = tab === "logs" || tab === "shell" || tab === "sql";

  return (
    <Card
      className={cn(
        "flex flex-col",
        bounded
          ? "max-h-[calc(100dvh-12rem)] overflow-hidden lg:sticky lg:top-20 lg:h-[calc(100dvh-14.5rem)]"
          : "overflow-visible",
      )}
    >
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

        {/* Actions — Re-deploy / Start / Stop / Clone / Delete on one line.
            (Open app lives in the persistent instance header above.) */}
        <div className="flex flex-wrap items-center gap-2">
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
          {onDelete && (
            <Button size="sm" variant="danger" onClick={onDelete}>
              <Trash2 className="size-4" />
              Delete
            </Button>
          )}
        </div>
      </div>

      {/* Section tabs — every tool (Metrics / Databases / Code / Shell / SQL /
          Logs / Snapshots) swaps in place below, so the workspace never
          navigates away from the environment. */}
      <SectionTabBar tab={tab} setTab={setTab} />

      {/* Body — for console sections this flex-fills the bounded card (only this
          area scrolls); for content sections it flows so the page scrolls and
          nothing is clipped under the tabs. */}
      <div className={cn("flex min-h-0 flex-1 flex-col", bounded && "overflow-hidden")}>
      <div className={cn("min-h-0 flex-1 p-5", bounded && "overflow-y-auto")}>
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
        ) : tab === "overview" ? (
          <>
            {project.repo_url && (
              <RepoCard repoUrl={project.repo_url} branch={env.branch} cloneCmd={cloneCmd} />
            )}

            {/* Deployment history — Odoo.sh-style build timeline with per-build
                status and the failure reason for any failed deploy.
                (Live CPU/RAM/Disk live in the Metrics tab, not the Overview.) */}
            <DeploymentHistory instanceId={env.id} />
          </>
        ) : tab === "metrics" ? (
          <Metrics embedId={env.id} />
        ) : tab === "databases" ? (
          <Databases embedId={env.id} />
        ) : tab === "code" ? (
          // Code & packages is project-wide (bound to Production), inherited by
          // Staging/Development — so it always targets the Production instance.
          <Code embedId={project.production.id} />
        ) : tab === "shell" ? (
          <ShellPage embedId={env.id} />
        ) : tab === "sql" ? (
          <SqlPage embedId={env.id} />
        ) : tab === "logs" ? (
          <Logs embedId={env.id} />
        ) : tab === "snapshots" ? (
          <Backups embedId={env.id} />
        ) : null}
      </div>
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
