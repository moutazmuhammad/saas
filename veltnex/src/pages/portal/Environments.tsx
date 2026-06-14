import * as React from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  GitBranch,
  GitMerge,
  Plus,
  Trash2,
  ExternalLink,
  Rocket,
  FlaskConical,
  Server,
  Link2,
  GripVertical,
  ArrowRight,
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
} from "@/lib/api";

const TRANSIENT = new Set([
  "pending_payment",
  "paid",
  "pending_provision",
  "provisioning",
]);

const STAGE_META = {
  production: { icon: Server, accent: "text-success", ring: "ring-success/40" },
  staging: { icon: FlaskConical, accent: "text-info", ring: "ring-info/40" },
  development: { icon: Rocket, accent: "text-primary-glow", ring: "ring-primary-glow/40" },
} as const;

export default function Environments() {
  const { id = "" } = useParams();
  const instanceId = Number(id);
  const navigate = useNavigate();
  const toast = useToast();
  const [data, setData] = React.useState<ProjectEnvironments | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [createType, setCreateType] =
    React.useState<"staging" | "development" | null>(null);
  const [deleteTarget, setDeleteTarget] = React.useState<EnvChild | null>(null);
  const [mergePrompt, setMergePrompt] =
    React.useState<{ source: EnvChild; target: EnvChild } | null>(null);
  // Drag-and-drop merge state.
  const [draggingId, setDraggingId] = React.useState<number | null>(null);
  const [dragOverId, setDragOverId] = React.useState<number | null>(null);

  const load = React.useCallback(async () => {
    try {
      setData(await api.environments(instanceId));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not load environments.");
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

  const cycle = data?.billing_cycle === "yearly" ? "yr" : "mo";
  const prodId = data?.production.id ?? instanceId;
  const allEnvs: EnvChild[] = data
    ? [data.production, ...data.environments]
    : [];
  const staging = data?.environments.filter((e) => e.environment === "staging") ?? [];
  const development =
    data?.environments.filter((e) => e.environment === "development") ?? [];
  const canCreate = !!data?.has_repo;

  const onDrop = (target: EnvChild) => {
    const source = allEnvs.find((e) => e.id === draggingId) || null;
    setDraggingId(null);
    setDragOverId(null);
    if (source && source.id !== target.id) setMergePrompt({ source, target });
  };

  const cardProps = (env: EnvChild) => ({
    env,
    mainBranch: data?.main_branch || "main",
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
    onDragLeave: () =>
      setDragOverId((prev) => (prev === env.id ? null : prev)),
    onDrop: (e: React.DragEvent) => {
      e.preventDefault();
      onDrop(env);
    },
    onOpen: () => navigate(`/my/instances/${env.id}`),
    onDelete: env.is_production ? undefined : () => setDeleteTarget(env),
  });

  return (
    <div className="animate-fade-in">
      <PortalBreadcrumb
        items={[
          { label: "Instances", to: "/my/instances" },
          { label: data?.production.name || "Project", to: `/my/instances/${prodId}` },
          { label: "Environments" },
        ]}
      />

      <div>
        <h1 className="text-2xl font-bold tracking-tight">Environments</h1>
        <p className="mt-1 text-sm text-muted">
          Your project's servers, organised by stage — just like Odoo.sh. Open a
          server to manage it, or <strong className="text-foreground">drag one
          server onto another to merge its branch</strong> and redeploy.
        </p>
      </div>

      {error && (
        <AlertBanner className="mt-6" variant="danger" title="Environments" description={error} />
      )}

      {!data && !error ? (
        <div className="mt-20 flex justify-center">
          <Spinner size="lg" label="Loading environments…" />
        </div>
      ) : data ? (
        <>
          {!canCreate && (
            <Card className="mt-6 flex flex-col gap-3 border-info/40 bg-info/5 p-5 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-start gap-3">
                <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-info/10 text-info">
                  <Link2 className="size-5" />
                </span>
                <div>
                  <p className="font-medium">Connect a Git repository to get started</p>
                  <p className="text-xs text-muted">
                    Staging and Development servers run on branches of your repo.
                    Link a repository to Production to unlock them.
                  </p>
                </div>
              </div>
              <Button className="shrink-0" onClick={() => navigate(`/my/instances/${prodId}/code`)}>
                <GitBranch className="size-4" />
                Connect repository
              </Button>
            </Card>
          )}

          {/* Project facts */}
          <div className="mt-6 flex flex-wrap items-center gap-x-6 gap-y-2 text-xs text-muted">
            <span className="inline-flex items-center gap-1.5">
              <GitBranch className="size-3.5" />
              Main branch:{" "}
              <code className="rounded bg-border/60 px-1 py-0.5 font-mono text-foreground">
                {data.main_branch}
              </code>
            </span>
            <span>
              Each extra Staging / Development server (lowest spec):{" "}
              <strong className="text-foreground">
                {data.env_server_price}/{cycle}
              </strong>
            </span>
          </div>

          {/* Odoo.sh-style three-stage board */}
          <div className="mt-5 grid gap-4 lg:grid-cols-3">
            <StageColumn
              stage="production"
              title="Production"
              hint="Always one server, on your main branch."
              count={1}
            >
              <EnvironmentCard {...cardProps(data.production)} />
            </StageColumn>

            <StageColumn
              stage="staging"
              title="Staging"
              hint="Pre-production copies on a chosen branch."
              count={staging.length}
              onAdd={canCreate ? () => setCreateType("staging") : undefined}
              addDisabledReason={canCreate ? undefined : "Connect a repository first"}
            >
              {staging.length === 0 ? (
                <EmptyStage label="No staging servers yet." />
              ) : (
                staging.map((env) => <EnvironmentCard key={env.id} {...cardProps(env)} />)
              )}
            </StageColumn>

            <StageColumn
              stage="development"
              title="Development"
              hint="Throwaway servers, each on its own branch."
              count={development.length}
              onAdd={canCreate ? () => setCreateType("development") : undefined}
              addDisabledReason={canCreate ? undefined : "Connect a repository first"}
            >
              {development.length === 0 ? (
                <EmptyStage label="No development servers yet." />
              ) : (
                development.map((env) => <EnvironmentCard key={env.id} {...cardProps(env)} />)
              )}
            </StageColumn>
          </div>

          {canCreate && allEnvs.length > 1 && (
            <p className="mt-4 flex items-center gap-1.5 text-xs text-muted">
              <GitMerge className="size-3.5" />
              Tip: drag a server card onto another to merge its branch into that
              server and redeploy it.
            </p>
          )}
        </>
      ) : null}

      <CreateEnvDialog
        instanceId={instanceId}
        type={createType}
        onClose={() => setCreateType(null)}
        onCreated={(auto) => {
          setCreateType(null);
          if (auto)
            toast.success("Environment created", "We're provisioning your new server now.");
          load();
        }}
      />

      <DeleteEnvDialog
        instanceId={instanceId}
        env={deleteTarget}
        onClose={() => setDeleteTarget(null)}
        onDeleted={() => {
          setDeleteTarget(null);
          toast.success("Environment removed", "The server is being torn down.");
          load();
        }}
      />

      <MergeEnvDialog
        instanceId={instanceId}
        prompt={mergePrompt}
        onClose={() => setMergePrompt(null)}
        onMerged={(msg) => {
          setMergePrompt(null);
          toast.success("Merge complete", msg);
          load();
        }}
      />
    </div>
  );
}

function StageColumn({
  stage,
  title,
  hint,
  count,
  onAdd,
  addDisabledReason,
  children,
}: {
  stage: keyof typeof STAGE_META;
  title: string;
  hint: string;
  count: number;
  onAdd?: () => void;
  addDisabledReason?: string;
  children: React.ReactNode;
}) {
  const { icon: Icon, accent } = STAGE_META[stage];
  return (
    <div className="flex flex-col rounded-xl border border-border bg-card/40 p-3">
      <div className="flex items-center justify-between gap-2 px-1">
        <div className="flex items-center gap-2">
          <Icon className={cn("size-4", accent)} />
          <h2 className="text-sm font-semibold">{title}</h2>
          <span className="rounded-full bg-border/60 px-1.5 py-0.5 text-[11px] font-medium text-muted">
            {count}
          </span>
        </div>
        {(onAdd || addDisabledReason) && (
          <Button size="sm" variant="ghost" onClick={onAdd} disabled={!onAdd} title={addDisabledReason}>
            <Plus className="size-4" />
            Add
          </Button>
        )}
      </div>
      <p className="mt-0.5 px-1 text-xs text-muted">{hint}</p>
      <div className="mt-3 flex flex-1 flex-col gap-2.5">{children}</div>
    </div>
  );
}

function EmptyStage({ label }: { label: string }) {
  return (
    <div className="flex flex-1 items-center justify-center rounded-lg border border-dashed border-border p-6 text-center text-xs text-muted">
      {label}
    </div>
  );
}

function EnvironmentCard({
  env,
  mainBranch,
  draggable,
  isDragging,
  isDropTarget,
  onDragStart,
  onDragEnd,
  onDragOver,
  onDragLeave,
  onDrop,
  onOpen,
  onDelete,
}: {
  env: EnvChild;
  mainBranch: string;
  draggable: boolean;
  isDragging: boolean;
  isDropTarget: boolean;
  onDragStart: () => void;
  onDragEnd: () => void;
  onDragOver: (e: React.DragEvent) => void;
  onDragLeave: () => void;
  onDrop: (e: React.DragEvent) => void;
  onOpen: () => void;
  onDelete?: () => void;
}) {
  const { icon: Icon, ring } = STAGE_META[env.environment];
  return (
    <Card
      draggable={draggable}
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
      className={cn(
        "group flex flex-col gap-2.5 p-3.5 transition-all",
        draggable && "cursor-grab active:cursor-grabbing",
        isDragging && "opacity-40",
        isDropTarget && cn("ring-2", ring),
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex min-w-0 items-start gap-2.5">
          {draggable && (
            <GripVertical className="mt-0.5 size-4 shrink-0 text-muted/50 transition-colors group-hover:text-muted" />
          )}
          <span className="flex size-8 shrink-0 items-center justify-center rounded-lg border border-border bg-card text-muted">
            <Icon className="size-4" />
          </span>
          <div className="min-w-0">
            <p className="truncate font-medium leading-tight">{env.name}</p>
            <p className="mt-1 flex items-center gap-1.5 truncate text-xs text-muted">
              <GitBranch className="size-3 shrink-0" />
              <span className="truncate">{env.branch || mainBranch}</span>
            </p>
          </div>
        </div>
        <StatusBadge status={env.state} />
      </div>

      <div className="flex items-center justify-end gap-1.5">
        {env.pending_payment && env.pending_invoice_id ? (
          <Button
            size="sm"
            onClick={() => (window.location.href = `/my/instances/${env.id}/checkout`)}
          >
            Complete checkout
          </Button>
        ) : (
          <Button size="sm" variant="secondary" onClick={onOpen}>
            <ExternalLink className="size-4" />
            Open
          </Button>
        )}
        {onDelete && (
          <Button size="sm" variant="ghost" onClick={onDelete} title="Remove server">
            <Trash2 className="size-4 text-danger" />
          </Button>
        )}
      </div>
    </Card>
  );
}

function MergeEnvDialog({
  instanceId,
  prompt,
  onClose,
  onMerged,
}: {
  instanceId: number;
  prompt: { source: EnvChild; target: EnvChild } | null;
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
      const res = await api.environmentMerge(
        instanceId,
        prompt.source.id,
        prompt.target.id,
      );
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

  const toProd = prompt?.target.is_production;

  return (
    <Dialog open={!!prompt} onClose={onClose} title="Merge branches">
      {error && (
        <AlertBanner className="mb-4" variant="danger" title="Couldn't merge" description={error} />
      )}
      {prompt && (
        <>
          <div className="flex items-center justify-center gap-3 rounded-lg border border-border bg-card/50 p-4">
            <BranchPill name={prompt.source.name} branch={prompt.source.branch} />
            <ArrowRight className="size-5 shrink-0 text-muted" />
            <BranchPill name={prompt.target.name} branch={prompt.target.branch} highlight />
          </div>
          <p className="mt-4 text-sm text-muted">
            This merges branch{" "}
            <code className="rounded bg-border/60 px-1 py-0.5 font-mono text-xs text-foreground">
              {prompt.source.branch}
            </code>{" "}
            into{" "}
            <code className="rounded bg-border/60 px-1 py-0.5 font-mono text-xs text-foreground">
              {prompt.target.branch}
            </code>{" "}
            on your Git host, then redeploys <strong>{prompt.target.name}</strong> with the
            merged code.
          </p>
          {toProd && (
            <AlertBanner
              className="mt-4"
              variant="warning"
              title="This targets Production"
              description="The merged code will be deployed to your live Production server."
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

function BranchPill({
  name,
  branch,
  highlight,
}: {
  name: string;
  branch: string;
  highlight?: boolean;
}) {
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
  onCreated: (autoProvisioned: boolean) => void;
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
      api
        .instanceBranches(instanceId)
        .then((b) => setBranches(b.branches))
        .catch(() => setBranches([]));
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
      onCreated(!!res.auto_provisioned);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't create the environment.");
      setLoading(false);
    }
  };

  const title = isStaging ? "New staging server" : "New development server";

  return (
    <Dialog open={!!type} onClose={onClose} title={title}>
      {error && (
        <AlertBanner className="mb-4" variant="danger" title="Couldn't create" description={error} />
      )}
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
            <p className="text-xs text-muted">
              Attach this staging server to an existing branch, or leave it to create a fresh one.
            </p>
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
      {error && (
        <AlertBanner className="mb-4" variant="danger" title="Couldn't remove" description={error} />
      )}
      <div className="flex gap-3">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-danger/10 text-danger">
          <Trash2 className="size-5" />
        </span>
        <div className="text-sm">
          <p className="font-medium text-foreground">
            Remove the {env?.environment_label.toLowerCase()} server <strong>{env?.name}</strong>?
          </p>
          <p className="mt-1 text-muted">
            The server and its data are deleted. Any unused time on your current cycle is credited
            back to your wallet. This can't be undone.
          </p>
        </div>
      </div>
      <label className="mt-5 flex items-start gap-2.5 rounded-lg border border-border p-3 text-sm">
        <input
          type="checkbox"
          className="mt-0.5"
          checked={deleteBranch}
          onChange={(e) => setDeleteBranch(e.target.checked)}
        />
        <span>
          Also delete the Git branch{" "}
          <code className="rounded bg-border/60 px-1 py-0.5 font-mono text-xs text-foreground">
            {env?.branch}
          </code>{" "}
          on the remote. Leave unchecked to keep your branch.
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
