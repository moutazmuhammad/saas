import * as React from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  Boxes,
  GitBranch,
  Plus,
  Trash2,
  ExternalLink,
  Rocket,
  FlaskConical,
  Server,
} from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/input";
import { Dialog } from "@/components/ui/dialog";
import { ActionButton } from "@/components/ActionButton";
import { AlertBanner } from "@/components/AlertBanner";
import { StatusBadge } from "@/components/StatusBadge";
import { EmptyState } from "@/components/EmptyState";
import { Spinner } from "@/components/Spinner";
import { PortalBreadcrumb } from "@/components/layout/PortalLayout";
import { useToast } from "@/context/ToastContext";
import {
  api,
  ApiError,
  type EnvChild,
  type ProjectEnvironments,
} from "@/lib/api";

// States that mean a server is still settling — poll while any child is here.
const TRANSIENT = new Set([
  "pending_payment",
  "paid",
  "pending_provision",
  "provisioning",
]);

export default function Environments() {
  const { id = "" } = useParams();
  const instanceId = Number(id);
  const toast = useToast();
  const [data, setData] = React.useState<ProjectEnvironments | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [createType, setCreateType] =
    React.useState<"staging" | "development" | null>(null);
  const [deleteTarget, setDeleteTarget] = React.useState<EnvChild | null>(null);

  const load = React.useCallback(async () => {
    try {
      setData(await api.environments(instanceId));
    } catch (e) {
      setError(
        e instanceof ApiError ? e.message : "Could not load environments.",
      );
    }
  }, [instanceId]);

  React.useEffect(() => {
    load();
  }, [load]);

  // Poll while any environment is provisioning / awaiting payment.
  const hasTransient = !!data?.environments.some((c) => TRANSIENT.has(c.state));
  React.useEffect(() => {
    if (!hasTransient) return;
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [hasTransient, load]);

  const cycle = data?.billing_cycle === "yearly" ? "yr" : "mo";

  return (
    <div className="animate-fade-in">
      <PortalBreadcrumb
        items={[
          { label: "Instances", to: "/my/instances" },
          { label: "Instance", to: `/my/instances/${id}` },
          { label: "Environments" },
        ]}
      />

      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Environments</h1>
          <p className="mt-1 text-sm text-muted">
            One Production server plus any number of Staging and Development
            servers — each on its own Git branch, like Odoo.sh.
          </p>
        </div>
        {data && (
          <div className="flex gap-2">
            <Button variant="secondary" onClick={() => setCreateType("staging")}>
              <Plus className="size-4" />
              New staging
            </Button>
            <Button onClick={() => setCreateType("development")}>
              <Plus className="size-4" />
              New development
            </Button>
          </div>
        )}
      </div>

      {error && (
        <AlertBanner
          className="mt-6"
          variant="danger"
          title="Environments"
          description={error}
        />
      )}

      {!data && !error ? (
        <div className="mt-20 flex justify-center">
          <Spinner size="lg" label="Loading environments…" />
        </div>
      ) : data ? (
        <>
          <p className="mt-6 text-xs text-muted">
            Each additional Staging or Development server costs{" "}
            <strong className="text-foreground">
              {data.env_server_price}/{cycle}
            </strong>{" "}
            and is added to your subscription.
          </p>

          {/* Production */}
          <h2 className="mt-6 text-sm font-semibold text-muted">Production</h2>
          <div className="mt-2">
            <EnvironmentCard
              env={data.production}
              mainBranch={data.main_branch}
            />
          </div>

          {/* Staging / Development */}
          <h2 className="mt-8 text-sm font-semibold text-muted">
            Staging &amp; Development
          </h2>
          {data.environments.length === 0 ? (
            <EmptyState
              className="mt-2"
              icon={Boxes}
              title="No extra environments yet"
              description="Spin up a Staging or Development server in one click. We provision it automatically and wire it to its Git branch."
            />
          ) : (
            <div className="mt-2 grid gap-4 sm:grid-cols-2">
              {data.environments.map((env) => (
                <EnvironmentCard
                  key={env.id}
                  env={env}
                  mainBranch={data.main_branch}
                  onDelete={() => setDeleteTarget(env)}
                />
              ))}
            </div>
          )}
        </>
      ) : null}

      <CreateEnvDialog
        instanceId={instanceId}
        type={createType}
        onClose={() => setCreateType(null)}
        onCreated={(autoProvisioned) => {
          setCreateType(null);
          if (autoProvisioned)
            toast.success(
              "Environment created",
              "We're provisioning your new server now.",
            );
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
    </div>
  );
}

function EnvironmentCard({
  env,
  mainBranch,
  onDelete,
}: {
  env: EnvChild;
  mainBranch: string;
  onDelete?: () => void;
}) {
  const navigate = useNavigate();
  const Icon = env.is_production
    ? Server
    : env.environment === "staging"
      ? FlaskConical
      : Rocket;
  return (
    <Card className="flex flex-col gap-3 p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <span className="flex size-10 shrink-0 items-center justify-center rounded-lg border border-border bg-card text-muted">
            <Icon className="size-4" />
          </span>
          <div>
            <div className="flex items-center gap-2">
              <p className="font-medium">{env.name}</p>
              <span className="rounded-full border border-border px-2 py-0.5 text-[11px] text-muted">
                {env.environment_label}
              </span>
            </div>
            <p className="mt-0.5 flex items-center gap-1.5 text-xs text-muted">
              <GitBranch className="size-3" />
              {env.branch || mainBranch}
            </p>
          </div>
        </div>
        <StatusBadge status={env.state} />
      </div>

      <div className="flex items-center justify-end gap-2">
        {env.pending_payment && env.pending_invoice_id ? (
          <Button
            size="sm"
            onClick={() =>
              (window.location.href = `/my/instances/${env.id}/checkout`)
            }
          >
            Complete checkout
          </Button>
        ) : (
          <Button
            size="sm"
            variant="secondary"
            onClick={() => navigate(`/my/instances/${env.id}`)}
          >
            <ExternalLink className="size-4" />
            Open
          </Button>
        )}
        {onDelete && (
          <Button size="sm" variant="ghost" onClick={onDelete}>
            <Trash2 className="size-4 text-danger" />
          </Button>
        )}
      </div>
    </Card>
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
    // Staging may attach to an existing branch — offer a picker.
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
      setError(
        e instanceof ApiError ? e.message : "Couldn't create the environment.",
      );
      setLoading(false);
    }
  };

  const title = isStaging
    ? "New staging server"
    : "New development server";

  return (
    <Dialog open={!!type} onClose={onClose} title={title}>
      {error && (
        <AlertBanner
          className="mb-4"
          variant="danger"
          title="Couldn't create"
          description={error}
        />
      )}
      <div className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="env-name">
            {isStaging ? "Server name" : "Server / branch name"}
          </Label>
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
              Attach this staging server to an existing branch, or leave it to
              create a fresh one.
            </p>
          </div>
        )}
      </div>
      <div className="mt-6 flex justify-end gap-2">
        <Button variant="secondary" onClick={onClose} disabled={loading}>
          Cancel
        </Button>
        <ActionButton
          loading={loading}
          loadingText="Creating…"
          disabled={!ok}
          onClick={submit}
        >
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
      setError(
        e instanceof ApiError ? e.message : "Couldn't remove the environment.",
      );
      setLoading(false);
    }
  };

  return (
    <Dialog open={!!env} onClose={onClose} title="Remove environment">
      {error && (
        <AlertBanner
          className="mb-4"
          variant="danger"
          title="Couldn't remove"
          description={error}
        />
      )}
      <div className="flex gap-3">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-danger/10 text-danger">
          <Trash2 className="size-5" />
        </span>
        <div className="text-sm">
          <p className="font-medium text-foreground">
            Remove the {env?.environment_label.toLowerCase()} server{" "}
            <strong>{env?.name}</strong>?
          </p>
          <p className="mt-1 text-muted">
            The server and its data are deleted. Any unused time on your current
            cycle is credited back to your wallet. This can't be undone.
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
        <ActionButton
          variant="danger"
          loading={loading}
          loadingText="Removing…"
          onClick={submit}
        >
          Remove server
        </ActionButton>
      </div>
    </Dialog>
  );
}
