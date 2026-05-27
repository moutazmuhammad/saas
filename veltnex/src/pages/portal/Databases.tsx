import * as React from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  Plus,
  Database,
  KeyRound,
  Trash2,
  ExternalLink,
  Copy,
  Check,
  MoreHorizontal,
  Loader2,
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
import { api, ApiError, type DbListData } from "@/lib/api";
import { cn } from "@/lib/utils";

type Banner = { variant: "success" | "danger" | "info"; title: string; description?: string };

export default function Databases() {
  const { id = "" } = useParams();
  const instanceId = Number(id);
  const navigate = useNavigate();
  const toast = useToast();

  const [data, setData] = React.useState<DbListData | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [banner, setBanner] = React.useState<Banner | null>(null);
  const [createOpen, setCreateOpen] = React.useState(false);
  const [resetTarget, setResetTarget] = React.useState<string | null>(null);
  const [openMenu, setOpenMenu] = React.useState<string | null>(null);

  const load = React.useCallback(async () => {
    try {
      const d = await api.databases(instanceId);
      setData(d);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not load databases.");
    }
  }, [instanceId]);

  React.useEffect(() => {
    load();
  }, [load]);

  // While async create/drop ops are in flight, poll until they settle.
  const hasPending = !!data?.pending_ops?.length;
  React.useEffect(() => {
    if (!hasPending) return;
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [hasPending, load]);

  const handleDrop = async (name: string) => {
    setOpenMenu(null);
    if (!confirm(`Delete database "${name}"? This cannot be undone.`)) return;
    try {
      await api.dbDrop(instanceId, name);
      setBanner({ variant: "info", title: "Deleting database…", description: `${name} is being removed.` });
      load();
    } catch (e) {
      setBanner({ variant: "danger", title: "Couldn't delete", description: e instanceof ApiError ? e.message : "" });
    }
  };

  return (
    <div className="animate-fade-in">
      <PortalBreadcrumb
        items={[
          { label: "Instances", to: "/my/instances" },
          { label: "Instance", to: `/my/instances/${id}` },
          { label: "Databases" },
        ]}
      />

      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Databases</h1>
          <p className="mt-1 text-sm text-muted">Create, back up, and manage your databases.</p>
        </div>
        <Button onClick={() => setCreateOpen(true)} disabled={!data?.ready}>
          <Plus className="size-4" />
          Create database
        </Button>
      </div>

      {banner && (
        <AlertBanner className="mt-6" variant={banner.variant} title={banner.title} description={banner.description} onDismiss={() => setBanner(null)} />
      )}
      {error && <AlertBanner className="mt-6" variant="danger" title="Database management" description={error} />}

      {data?.pending_ops?.map((op) => (
        <AlertBanner
          key={op.db_name}
          className="mt-4"
          variant="info"
          title={`${op.operation === "drop" ? "Deleting" : "Creating"} ${op.db_name}…`}
          description="This usually takes about a minute. The list updates automatically."
        />
      ))}

      {!data && !error ? (
        <div className="mt-20 flex justify-center">
          <Spinner size="lg" label="Loading databases…" />
        </div>
      ) : data && !data.ready ? (
        <EmptyState
          className="mt-8"
          icon={Database}
          title="Instance not ready"
          description="Database management becomes available once your instance is running."
          action={<Button variant="secondary" onClick={() => navigate(`/my/instances/${id}`)}>Back to instance</Button>}
        />
      ) : data && data.databases.length === 0 ? (
        <EmptyState
          className="mt-8"
          icon={Database}
          title="No databases yet"
          description="Create your first database to start using this instance."
          action={<Button onClick={() => setCreateOpen(true)}>Create database</Button>}
        />
      ) : data ? (
        <Card className="mt-6 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted">
                  <th className="px-5 py-3 font-medium">Name</th>
                  <th className="hidden px-5 py-3 font-medium sm:table-cell">Admin login</th>
                  <th className="px-5 py-3 font-medium">Status</th>
                  <th className="px-5 py-3 text-right font-medium">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {data.databases.map((db) => {
                  const pending = data.pending_ops?.some((o) => o.db_name === db.name);
                  return (
                    <tr key={db.name} className="transition-colors hover:bg-card/60">
                      <td className="px-5 py-4">
                        <div className="flex items-center gap-2.5">
                          <Database className="size-4 text-muted" />
                          <span className="font-medium">{db.name}</span>
                        </div>
                      </td>
                      <td className="hidden px-5 py-4 text-muted sm:table-cell">{db.login || "—"}</td>
                      <td className="px-5 py-4">
                        {pending ? (
                          <span className="inline-flex items-center gap-1.5 text-xs text-info">
                            <Loader2 className="size-3.5 animate-spin" /> Working…
                          </span>
                        ) : (
                          <StatusBadge status="running" label="Active" />
                        )}
                      </td>
                      <td className="px-5 py-4">
                        <div className="flex items-center justify-end gap-1">
                          <Button
                            size="sm"
                            variant="ghost"
                            disabled={pending}
                            onClick={() => window.open(`https://${db.name}`, "_blank")}
                          >
                            <ExternalLink className="size-4" />
                            <span className="hidden lg:inline">Open</span>
                          </Button>
                          <div className="relative">
                            <Button size="icon" variant="ghost" disabled={pending} onClick={() => setOpenMenu(openMenu === db.name ? null : db.name)} aria-label="More actions">
                              <MoreHorizontal className="size-4" />
                            </Button>
                            {openMenu === db.name && (
                              <>
                                <div className="fixed inset-0 z-10" onClick={() => setOpenMenu(null)} />
                                <div className="absolute right-0 z-20 mt-1 w-44 overflow-hidden rounded-lg border border-border bg-card shadow-card animate-scale-in">
                                  <MenuItem icon={KeyRound} label="Reset password" onClick={() => { setOpenMenu(null); setResetTarget(db.name); }} />
                                  <div className="border-t border-border" />
                                  <MenuItem icon={Trash2} label="Delete" danger onClick={() => handleDrop(db.name)} />
                                </div>
                              </>
                            )}
                          </div>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Card>
      ) : null}

      <CreateDatabaseDialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        existing={data?.databases.map((d) => d.name) || []}
        onCreate={async (name, login, password) => {
          await api.dbCreate(instanceId, name, login, password);
          toast.success("Creating database", `${name} is being provisioned.`);
          setBanner({ variant: "info", title: "Creating database…", description: `${name} will appear shortly.` });
          load();
        }}
      />

      <ResetPasswordDialog
        dbName={resetTarget}
        onClose={() => setResetTarget(null)}
        onReset={async (name, password) => {
          await api.dbResetPassword(instanceId, name, password);
          toast.success("Password reset", `New admin password set for ${name}.`);
        }}
      />
    </div>
  );
}

function MenuItem({ icon: Icon, label, onClick, danger }: { icon: typeof KeyRound; label: string; onClick: () => void; danger?: boolean }) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "flex w-full items-center gap-2.5 px-3 py-2.5 text-left text-sm transition-colors",
        danger ? "text-danger hover:bg-danger/10" : "text-foreground hover:bg-border/50"
      )}
    >
      <Icon className="size-4" />
      {label}
    </button>
  );
}

function CreateDatabaseDialog({
  open,
  onClose,
  existing,
  onCreate,
}: {
  open: boolean;
  onClose: () => void;
  existing: string[];
  onCreate: (name: string, login: string, password: string) => Promise<void>;
}) {
  const [name, setName] = React.useState("");
  const [login, setLogin] = React.useState("admin");
  const [password, setPassword] = React.useState("");
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (open) {
      setName("");
      setLogin("admin");
      setPassword("");
      setError(null);
      setLoading(false);
    }
  }, [open]);

  const submit = async () => {
    if (!/^[a-z][a-z0-9_]{2,40}$/.test(name)) {
      return setError("Use 3–41 lowercase letters, numbers, or underscores, starting with a letter.");
    }
    if (existing.includes(name)) return setError("A database with that name already exists.");
    if (password.length < 6) return setError("Choose an admin password of at least 6 characters.");
    setError(null);
    setLoading(true);
    try {
      await onCreate(name, login, password);
      onClose();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't create the database.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} title="Create database" description="Spin up a new Odoo database on this instance.">
      {error && <AlertBanner className="mb-4" variant="danger" title="Couldn't create database" description={error} />}
      <div className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="db-name">Database name</Label>
          <Input id="db-name" placeholder="production" value={name} autoFocus onChange={(e) => { setName(e.target.value.toLowerCase()); setError(null); }} />
        </div>
        <div className="space-y-2">
          <Label htmlFor="db-login">Admin login</Label>
          <Input id="db-login" placeholder="admin" value={login} onChange={(e) => setLogin(e.target.value)} />
        </div>
        <div className="space-y-2">
          <Label htmlFor="db-pass">Admin password</Label>
          <Input id="db-pass" type="password" placeholder="••••••••" value={password} onChange={(e) => setPassword(e.target.value)} />
        </div>
      </div>
      <div className="mt-6 flex justify-end gap-2">
        <Button variant="secondary" onClick={onClose} disabled={loading}>Cancel</Button>
        <ActionButton loading={loading} loadingText="Creating…" onClick={submit}>Create database</ActionButton>
      </div>
    </Dialog>
  );
}

function ResetPasswordDialog({
  dbName,
  onClose,
  onReset,
}: {
  dbName: string | null;
  onClose: () => void;
  onReset: (name: string, password: string) => Promise<void>;
}) {
  const [password, setPassword] = React.useState("");
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [done, setDone] = React.useState(false);
  const [copied, setCopied] = React.useState(false);

  React.useEffect(() => {
    if (dbName) {
      setPassword("");
      setError(null);
      setLoading(false);
      setDone(false);
      setCopied(false);
    }
  }, [dbName]);

  const submit = async () => {
    if (!dbName) return;
    if (password.length < 6) return setError("Choose a password of at least 6 characters.");
    setError(null);
    setLoading(true);
    try {
      await onReset(dbName, password);
      setDone(true);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't reset the password.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog open={!!dbName} onClose={onClose} title="Reset admin password" description={dbName ? `Set a new admin password for ${dbName}.` : undefined}>
      {!done ? (
        <>
          {error && <AlertBanner className="mb-4" variant="danger" title="Couldn't reset password" description={error} />}
          <AlertBanner variant="warning" title="This rotates the admin password" description="The admin user will need the new password to sign in." />
          <div className="mt-4 space-y-2">
            <Label htmlFor="new-pass">New password</Label>
            <Input id="new-pass" type="password" placeholder="••••••••" value={password} autoFocus onChange={(e) => setPassword(e.target.value)} onKeyDown={(e) => e.key === "Enter" && submit()} />
          </div>
          <div className="mt-6 flex justify-end gap-2">
            <Button variant="secondary" onClick={onClose} disabled={loading}>Cancel</Button>
            <ActionButton variant="danger" loading={loading} loadingText="Resetting…" onClick={submit}>Reset password</ActionButton>
          </div>
        </>
      ) : (
        <>
          <AlertBanner variant="success" title="Password reset" description="The admin password has been updated." />
          <div className="mt-4">
            <Label>New password</Label>
            <div className="mt-2 flex items-center gap-2 rounded-lg border border-border bg-background p-2.5">
              <code className="flex-1 truncate font-mono text-sm">{password}</code>
              <Button size="sm" variant="ghost" onClick={() => { navigator.clipboard?.writeText(password); setCopied(true); setTimeout(() => setCopied(false), 1500); }}>
                {copied ? <Check className="size-4 text-success" /> : <Copy className="size-4" />}
                {copied ? "Copied" : "Copy"}
              </Button>
            </div>
          </div>
          <div className="mt-6 flex justify-end">
            <Button onClick={onClose}>Done</Button>
          </div>
        </>
      )}
    </Dialog>
  );
}
