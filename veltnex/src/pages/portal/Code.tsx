import * as React from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { GitBranch, Package, Plus, X, Unplug, Boxes } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/input";
import { ActionButton } from "@/components/ActionButton";
import { AlertBanner } from "@/components/AlertBanner";
import { EmptyState } from "@/components/EmptyState";
import { Spinner } from "@/components/Spinner";
import { Dialog } from "@/components/ui/dialog";
import { HelpHint } from "@/components/HelpHint";
import { PortalBreadcrumb, envCrumbs } from "@/components/layout/PortalLayout";
import { useToast } from "@/context/ToastContext";
import { api, ApiError, type ApiInstance } from "@/lib/api";

const parsePkgs = (s?: string) =>
  (s || "").split("\n").map((l) => l.trim()).filter(Boolean);

export default function Code() {
  const { id = "" } = useParams();
  const instanceId = Number(id);
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const toast = useToast();

  const [instance, setInstance] = React.useState<ApiInstance | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  const load = React.useCallback(async () => {
    try {
      setInstance(await api.instance(instanceId, params.get("access_token") || undefined));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Instance not found.");
    }
  }, [instanceId, params]);

  React.useEffect(() => {
    load();
  }, [load]);

  // Code & packages is a hosting-only (self-managed) feature. Managed
  // services have no code access — bounce back to the instance overview.
  React.useEffect(() => {
    if (instance && !instance.is_hosting) {
      navigate(`/my/instances/${id}`, { replace: true });
    }
  }, [instance, id, navigate]);

  if (error) {
    return (
      <EmptyState className="mt-10" icon={GitBranch} title="Unavailable" description={error} />
    );
  }
  if (!instance) {
    return (
      <div className="mt-20 flex justify-center"><Spinner size="lg" label="Loading…" /></div>
    );
  }

  const canDeploy = instance.state === "running" || instance.state === "stopped";

  return (
    <div className="animate-fade-in">
      <PortalBreadcrumb items={envCrumbs(instance, "Code & packages", id)} />

      <div>
        <h1 className="text-2xl font-bold tracking-tight">
          Code &amp; packages
          <HelpHint anchor="repo" className="ml-1.5" />
        </h1>
        <p className="mt-1 text-sm text-muted">
          Connect your Git modules and manage Python packages. Applying a change pulls your
          code and restarts the instance (brief downtime).
        </p>
      </div>

      {!canDeploy && (
        <AlertBanner
          className="mt-6"
          variant="warning"
          title="Can't deploy right now"
          description="The instance must be running or stopped to apply code or package changes."
        />
      )}

      <RepoSection instance={instance} disabled={!canDeploy} onDeployed={() => navigate(`/my/instances/${id}`)} />
      <PackagesSection instance={instance} disabled={!canDeploy} reload={load} />
    </div>
  );
}

function RepoSection({
  instance,
  disabled,
  onDeployed,
}: {
  instance: ApiInstance;
  disabled: boolean;
  onDeployed: () => void;
}) {
  const toast = useToast();
  const navigate = useNavigate();
  const repo = instance.repo || { url: "", branch: "main", has_token: false, state: "" };
  const connected = !!repo.url;
  // Repo + token are configured ONCE per project (Production). On a child
  // environment, the repo is inherited and read-only here.
  const isChild = !!instance.parent_id && instance.environment !== "production";
  const [url, setUrl] = React.useState(repo.url || "");
  const [branch, setBranch] = React.useState(repo.branch || "main");
  const [token, setToken] = React.useState("");
  const [saving, setSaving] = React.useState(false);
  const [confirmOff, setConfirmOff] = React.useState(false);

  const save = async () => {
    setSaving(true);
    try {
      const p: { repo_url: string; repo_branch: string; git_token?: string } = {
        repo_url: url.trim(),
        repo_branch: branch.trim() || "main",
      };
      if (token.trim()) p.git_token = token.trim();
      await api.setRepo(instance.id, p);
      toast.success("Deploying…", "Pulling your repository and restarting the instance.");
      onDeployed();
    } catch (e) {
      toast.error("Couldn't deploy", e instanceof ApiError ? e.message : "Please try again.");
      setSaving(false);
    }
  };

  const disconnect = async () => {
    setSaving(true);
    try {
      await api.setRepo(instance.id, { repo_url: "", repo_branch: "main" });
      toast.success("Disconnecting…", "Removing the repository and restarting the instance.");
      onDeployed();
    } catch (e) {
      toast.error("Couldn't disconnect", e instanceof ApiError ? e.message : "Please try again.");
      setSaving(false);
      setConfirmOff(false);
    }
  };

  // Child environment: the repo is inherited from the project (read-only).
  if (isChild) {
    return (
      <Card className="mt-6 p-5">
        <div className="flex items-center gap-3">
          <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/15 text-primary-glow">
            <GitBranch className="size-4" />
          </span>
          <div className="flex-1">
            <h2 className="font-semibold">Git repository</h2>
            <p className="text-xs text-muted">
              Inherited from the project. The repository and token are managed
              once on the Production environment.
            </p>
          </div>
          <Button
            variant="secondary"
            onClick={() => navigate(`/my/instances/${instance.parent_id}/code`)}
          >
            Manage on project
          </Button>
        </div>
        <div className="mt-5 grid gap-4 sm:grid-cols-2">
          <div>
            <Label>Repository</Label>
            <p className="mt-1 truncate font-mono text-sm text-muted">{repo.url || "—"}</p>
          </div>
          <div>
            <Label>Branch</Label>
            <p className="mt-1 font-mono text-sm text-muted">{repo.branch || "main"}</p>
          </div>
        </div>
      </Card>
    );
  }

  return (
    <Card className="mt-6 p-5">
      <div className="flex items-center gap-3">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/15 text-primary-glow">
          <GitBranch className="size-4" />
        </span>
        <div className="flex-1">
          <h2 className="font-semibold">Git repository</h2>
          <p className="text-xs text-muted">
            {connected
              ? "Your custom modules are deployed from this repository."
              : "Deploy your own Odoo modules from GitHub, GitLab or Bitbucket."}
          </p>
        </div>
        {connected && (
          <Button variant="secondary" disabled={disabled || saving} onClick={() => setConfirmOff(true)}>
            <Unplug className="size-4" />
            <span className="hidden sm:inline">Disconnect</span>
          </Button>
        )}
      </div>

      <div className="mt-5 space-y-4">
        <div>
          <Label htmlFor="repo-url">Repository URL</Label>
          <Input id="repo-url" value={url} onChange={(e) => setUrl(e.target.value)}
                 placeholder="https://github.com/you/your-odoo-modules.git" />
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <Label htmlFor="repo-branch">Branch</Label>
            <Input id="repo-branch" value={branch} onChange={(e) => setBranch(e.target.value)} placeholder="main" />
          </div>
          <div>
            <Label htmlFor="repo-token">
              Access token {repo.has_token && <span className="text-muted">(set — blank keeps it)</span>}
            </Label>
            <Input id="repo-token" type="password" value={token} onChange={(e) => setToken(e.target.value)}
                   placeholder={repo.has_token ? "••••••••" : "for private repositories"} />
          </div>
        </div>
      </div>

      <div className="mt-5 flex justify-end">
        <ActionButton loading={saving} loadingText="Deploying…" disabled={disabled || !url.trim()} onClick={save}>
          {connected ? "Save & redeploy" : "Connect & deploy"}
        </ActionButton>
      </div>

      <Dialog open={confirmOff} onClose={() => setConfirmOff(false)} title="Disconnect repository?">
        <p className="text-sm text-muted">
          This removes your custom modules from the instance and restarts it. Your databases and
          data are not affected. You can reconnect any time.
        </p>
        <div className="mt-6 flex justify-end gap-2">
          <Button variant="secondary" onClick={() => setConfirmOff(false)} disabled={saving}>Cancel</Button>
          <ActionButton variant="danger" loading={saving} loadingText="Disconnecting…" onClick={disconnect}>
            Disconnect
          </ActionButton>
        </div>
      </Dialog>
    </Card>
  );
}

function PackagesSection({
  instance,
  disabled,
  reload,
}: {
  instance: ApiInstance;
  disabled: boolean;
  reload: () => Promise<void> | void;
}) {
  const toast = useToast();
  const initial = React.useMemo(() => parsePkgs(instance.pip_packages), [instance.pip_packages]);
  const [pkgs, setPkgs] = React.useState<string[]>(initial);
  const [draft, setDraft] = React.useState("");
  const [saving, setSaving] = React.useState(false);
  const [installError, setInstallError] = React.useState<string>(instance.pip_install_error || "");

  const dirty = pkgs.join("\n") !== initial.join("\n");

  const add = () => {
    const v = draft.trim();
    if (!v) return;
    if (!pkgs.includes(v)) setPkgs([...pkgs, v]);
    setDraft("");
  };
  const remove = (p: string) => setPkgs(pkgs.filter((x) => x !== p));

  const apply = async () => {
    setSaving(true);
    setInstallError("");
    try {
      await api.setPackages(instance.id, pkgs.join("\n"));
      toast.success("Packages installed", "Your packages were installed and the instance restarted.");
      await reload();
    } catch (e) {
      // pip_failed carries the install output — show it inline, not just a toast.
      const msg = e instanceof ApiError ? e.message : "Please try again.";
      setInstallError(msg);
      toast.error("Package install failed", "See the details below.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card className="mt-6 p-5">
      <div className="flex items-center gap-3">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-info/15 text-info">
          <Package className="size-4" />
        </span>
        <div>
          <h2 className="font-semibold">Python packages</h2>
          <p className="text-xs text-muted">Extra pip packages your modules need. Remove any to uninstall it.</p>
        </div>
      </div>

      {installError && (
        <div className="mt-4">
          <AlertBanner
            variant="danger"
            title="Package install failed"
            description={
              <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap rounded-md bg-background/60 p-3 font-mono text-xs">
                {installError}
              </pre>
            }
            onDismiss={() => setInstallError("")}
          />
        </div>
      )}

      <div className="mt-5 flex gap-2">
        <Input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), add())}
          placeholder="e.g. requests or pandas==2.2.0"
        />
        <Button variant="secondary" onClick={add} disabled={!draft.trim()}>
          <Plus className="size-4" /> Add
        </Button>
      </div>

      {pkgs.length === 0 ? (
        <div className="mt-4 flex items-center gap-2 rounded-lg border border-dashed border-border p-4 text-sm text-muted">
          <Boxes className="size-4" /> No extra packages.
        </div>
      ) : (
        <div className="mt-4 flex flex-wrap gap-2">
          {pkgs.map((p) => (
            <span key={p} className="inline-flex items-center gap-1.5 rounded-full border border-border bg-card px-3 py-1 font-mono text-xs">
              {p}
              <button
                onClick={() => remove(p)}
                className="text-muted transition-colors hover:text-danger"
                aria-label={`Remove ${p}`}
              >
                <X className="size-3.5" />
              </button>
            </span>
          ))}
        </div>
      )}

      <div className="mt-5 flex items-center justify-between gap-3">
        <p className="text-xs text-muted">{dirty ? "Unsaved changes" : "Up to date"}</p>
        <ActionButton loading={saving} loadingText="Deploying…" disabled={disabled || !dirty} onClick={apply}>
          Apply &amp; redeploy
        </ActionButton>
      </div>
    </Card>
  );
}
