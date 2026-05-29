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
  Archive,
  Download,
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
import { api, ApiError, type DbListData, type ApiBackup } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

export default function Databases() {
  const { id = "" } = useParams();
  const instanceId = Number(id);
  const navigate = useNavigate();
  const toast = useToast();

  const [data, setData] = React.useState<DbListData | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [createOpen, setCreateOpen] = React.useState(false);
  const [resetTarget, setResetTarget] = React.useState<string | null>(null);
  const [dropTarget, setDropTarget] = React.useState<string | null>(null);
  const [backupsTarget, setBackupsTarget] = React.useState<string | null>(null);
  const [backups, setBackups] = React.useState<ApiBackup[]>([]);
  const [openMenu, setOpenMenu] = React.useState<string | null>(null);
  // The actions menu is rendered at fixed viewport coords (anchored to
  // the trigger button) so it isn't clipped by the table/card overflow
  // — which happened when a single short row left no room below it.
  const [menuPos, setMenuPos] = React.useState<{ top: number; right: number }>({ top: 0, right: 0 });

  const load = React.useCallback(async () => {
    try {
      const [d, b] = await Promise.all([
        api.databases(instanceId),
        api.backups(instanceId).catch(() => [] as ApiBackup[]),
      ]);
      setData(d);
      setBackups(b);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not load databases.");
    }
  }, [instanceId]);

  React.useEffect(() => {
    load();
  }, [load]);

  // Per-database, non-snapshot backups for a given DB name, newest first.
  const backupsFor = (name: string) =>
    backups.filter((b) => !b.is_full_instance && b.db_name === name);
  const backupRunning = backups.some((b) => b.status === "in_progress");

  // While async create/drop ops — or a backup — are in flight, poll.
  const hasPending = !!data?.pending_ops?.length || backupRunning;
  // Operation currently running against a given DB name (if any), so a
  // row can show the right label ("Creating…" vs "Deleting…").
  const pendingOp = (name: string) =>
    data?.pending_ops?.find((o) => o.db_name === name)?.operation;
  // A create that's mid-flight: while the DB hasn't appeared in the
  // list yet we surface it as a synthetic loading row. Once it shows up
  // in `databases` (mid-create), its own row carries the spinner — so
  // exclude those here to avoid a duplicate row.
  const existingNames = new Set((data?.databases ?? []).map((d) => d.name));
  const creatingOps = (data?.pending_ops ?? []).filter(
    (o) => o.operation === "create" && !existingNames.has(o.db_name),
  );
  // Any create in flight (existing-in-list or not) locks the button.
  const isCreating = (data?.pending_ops ?? []).some((o) => o.operation === "create");
  React.useEffect(() => {
    if (!hasPending) return;
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [hasPending, load]);

  // Runs the actual delete once confirmed in the dialog. Throws on
  // failure so the dialog can surface the error inline. No banner —
  // the row shows a "Deleting…" spinner until it's gone, mirroring
  // the create flow.
  const handleDrop = async (name: string) => {
    await api.dbDrop(instanceId, name);
    await load();
  };

  // Trigger a backup of one database, then reload so it shows up (and
  // becomes downloadable) right inside the per-database backups dialog.
  // Throws on failure so the dialog surfaces the error inline.
  const handleBackup = async (name: string) => {
    await api.dbBackup(instanceId, name);
    await load();
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
        <Button
          onClick={() => setCreateOpen(true)}
          disabled={!data?.ready || isCreating}
          title={isCreating ? "A database is already being created on this instance." : undefined}
        >
          {isCreating ? <Loader2 className="size-4 animate-spin" /> : <Plus className="size-4" />}
          {isCreating ? "Creating…" : "Create database"}
        </Button>
      </div>

      {error && <AlertBanner className="mt-6" variant="danger" title="Database management" description={error} />}

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
      ) : data && data.databases.length === 0 && !isCreating ? (
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
                {creatingOps.map((op) => (
                  <tr key={`creating-${op.db_name}`} className="bg-info/5">
                    <td className="px-5 py-4">
                      <div className="flex items-center gap-2.5">
                        <Database className="size-4 text-muted" />
                        <span className="font-medium">{op.db_name}</span>
                      </div>
                    </td>
                    <td className="hidden px-5 py-4 text-muted sm:table-cell">—</td>
                    <td className="px-5 py-4">
                      <span className="inline-flex items-center gap-1.5 text-xs text-info">
                        <Loader2 className="size-3.5 animate-spin" /> Creating…
                      </span>
                    </td>
                    <td className="px-5 py-4" />
                  </tr>
                ))}
                {data.databases.map((db) => {
                  const op = pendingOp(db.name);
                  const pending = !!op;
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
                            <Loader2 className="size-3.5 animate-spin" /> {op === "drop" ? "Deleting…" : "Creating…"}
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
                            disabled={pending || !data?.url}
                            title={data?.url ? undefined : "Instance URL unavailable"}
                            onClick={() =>
                              data?.url &&
                              window.open(
                                `${data.url.replace(/\/$/, "")}/web?db=${encodeURIComponent(db.name)}`,
                                "_blank",
                                "noopener,noreferrer",
                              )
                            }
                          >
                            <ExternalLink className="size-4" />
                            <span className="hidden lg:inline">Open</span>
                          </Button>
                          <div className="relative">
                            <Button
                              size="icon"
                              variant="ghost"
                              disabled={pending}
                              aria-label="More actions"
                              onClick={(e) => {
                                if (openMenu === db.name) {
                                  setOpenMenu(null);
                                  return;
                                }
                                const r = e.currentTarget.getBoundingClientRect();
                                setMenuPos({ top: r.bottom + 4, right: window.innerWidth - r.right });
                                setOpenMenu(db.name);
                              }}
                            >
                              <MoreHorizontal className="size-4" />
                            </Button>
                            {openMenu === db.name && (
                              <>
                                <div className="fixed inset-0 z-30" onClick={() => setOpenMenu(null)} />
                                <div
                                  className="fixed z-40 w-44 overflow-hidden rounded-lg border border-border bg-card shadow-card animate-scale-in"
                                  style={{ top: menuPos.top, right: menuPos.right }}
                                >
                                  <MenuItem icon={Archive} label="Backups" onClick={() => { setOpenMenu(null); setBackupsTarget(db.name); }} />
                                  <MenuItem icon={KeyRound} label="Reset password" onClick={() => { setOpenMenu(null); setResetTarget(db.name); }} />
                                  <div className="border-t border-border" />
                                  <MenuItem icon={Trash2} label="Delete" danger onClick={() => { setOpenMenu(null); setDropTarget(db.name); }} />
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
          // No banner/toast — the new DB now shows as a live "Creating…"
          // row in the list, and the Create button locks until it's done.
          await load();
        }}
      />

      <ResetPasswordDialog
        dbName={resetTarget}
        onClose={() => setResetTarget(null)}
        onReset={async (name, password, targetLogin) => {
          const { login } = await api.dbResetPassword(instanceId, name, password, targetLogin);
          toast.success("Password reset", `New admin password set for ${name}.`);
          return login;
        }}
      />

      <DeleteDatabaseDialog
        dbName={dropTarget}
        onClose={() => setDropTarget(null)}
        onConfirm={handleDrop}
      />

      <DatabaseBackupsDialog
        dbName={backupsTarget}
        backups={backupsTarget ? backupsFor(backupsTarget) : []}
        onBackup={handleBackup}
        onClose={() => setBackupsTarget(null)}
      />
    </div>
  );
}

function DatabaseBackupsDialog({
  dbName,
  backups,
  onBackup,
  onClose,
}: {
  dbName: string | null;
  backups: ApiBackup[];
  onBackup: (name: string) => Promise<void>;
  onClose: () => void;
}) {
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (dbName) {
      setLoading(false);
      setError(null);
    }
  }, [dbName]);

  const start = async () => {
    if (!dbName) return;
    setError(null);
    setLoading(true);
    try {
      await onBackup(dbName);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't start the backup.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog open={!!dbName} onClose={onClose} title="Backups" description={dbName ? `On-demand backups for “${dbName}”.` : undefined}>
      {error && <AlertBanner className="mb-4" variant="danger" title="Backup" description={error} />}
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm text-muted">
          {backups.length ? `${backups.length} backup${backups.length > 1 ? "s" : ""}` : "No backups yet for this database."}
        </p>
        <ActionButton loading={loading} loadingText="Starting…" onClick={start}>
          <Archive className="size-4" />
          Back up now
        </ActionButton>
      </div>
      {backups.length > 0 && (
        <div className="mt-4 divide-y divide-border overflow-hidden rounded-lg border border-border">
          {backups.map((b) => (
            <div key={b.id} className="flex items-center justify-between gap-3 px-3 py-2.5">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium">{formatDateTime(b.created)}</p>
                {b.status === "available" && b.size_mb > 0 && (
                  <p className="text-xs text-muted">{(b.size_mb / 1024).toFixed(2)} GB</p>
                )}
              </div>
              <div className="flex shrink-0 items-center gap-2">
                <StatusBadge status={b.status} />
                {b.status === "available" && b.download_url ? (
                  <a href={b.download_url} target="_blank" rel="noreferrer">
                    <Button size="sm" variant="ghost">
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
        </div>
      )}
      <div className="mt-6 flex justify-end">
        <Button variant="secondary" onClick={onClose}>Close</Button>
      </div>
    </Dialog>
  );
}

function DeleteDatabaseDialog({
  dbName,
  onClose,
  onConfirm,
}: {
  dbName: string | null;
  onClose: () => void;
  onConfirm: (name: string) => Promise<void>;
}) {
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [confirmText, setConfirmText] = React.useState("");

  React.useEffect(() => {
    if (dbName) {
      setLoading(false);
      setError(null);
      setConfirmText("");
    }
  }, [dbName]);

  const confirmed = confirmText.trim() === dbName;

  const submit = async () => {
    if (!dbName || !confirmed) return;
    setError(null);
    setLoading(true);
    try {
      await onConfirm(dbName);
      onClose();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't delete the database.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog open={!!dbName} onClose={onClose} title="Delete database">
      {error && <AlertBanner className="mb-4" variant="danger" title="Couldn't delete" description={error} />}
      <div className="flex gap-3">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-danger/10 text-danger">
          <Trash2 className="size-5" />
        </span>
        <div className="text-sm">
          <p className="font-medium text-foreground">
            Delete database “{dbName}”?
          </p>
          <p className="mt-1 text-muted">
            This permanently removes the database and all of its data. This action
            cannot be undone.
          </p>
        </div>
      </div>
      <div className="mt-5 space-y-2">
        <Label htmlFor="confirm-name">
          Type <code className="rounded bg-border/60 px-1 py-0.5 font-mono text-xs text-foreground">{dbName}</code> to confirm
        </Label>
        <Input
          id="confirm-name"
          autoFocus
          autoComplete="off"
          placeholder={dbName ?? ""}
          value={confirmText}
          onChange={(e) => setConfirmText(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && confirmed && submit()}
        />
      </div>
      <div className="mt-6 flex justify-end gap-2">
        <Button variant="secondary" onClick={onClose} disabled={loading}>Cancel</Button>
        <ActionButton variant="danger" loading={loading} loadingText="Deleting…" disabled={!confirmed} onClick={submit}>
          Delete database
        </ActionButton>
      </div>
    </Dialog>
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
  onReset: (name: string, password: string, targetLogin?: string) => Promise<string>;
}) {
  const [password, setPassword] = React.useState("");
  const [targetLogin, setTargetLogin] = React.useState("");
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [done, setDone] = React.useState(false);
  const [adminLogin, setAdminLogin] = React.useState("");
  const [copiedField, setCopiedField] = React.useState<"login" | "password" | null>(null);

  React.useEffect(() => {
    if (dbName) {
      setPassword("");
      setTargetLogin("");
      setError(null);
      setLoading(false);
      setDone(false);
      setAdminLogin("");
      setCopiedField(null);
    }
  }, [dbName]);

  const copy = (field: "login" | "password", value: string) => {
    navigator.clipboard?.writeText(value);
    setCopiedField(field);
    setTimeout(() => setCopiedField(null), 1500);
  };

  const submit = async () => {
    if (!dbName) return;
    if (password.length < 6) return setError("Choose a password of at least 6 characters.");
    setError(null);
    setLoading(true);
    try {
      const login = await onReset(dbName, password, targetLogin.trim() || undefined);
      setAdminLogin(login);
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
            <Label htmlFor="reset-login">Administrator login <span className="font-normal text-muted">(optional)</span></Label>
            <Input id="reset-login" placeholder="Leave blank to reset the main administrator" value={targetLogin} onChange={(e) => setTargetLogin(e.target.value)} />
            <p className="text-xs text-muted">If you replaced the default admin with your own user, enter that login. Otherwise leave this blank.</p>
          </div>
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
          <AlertBanner variant="success" title="Password reset" description="The admin password has been updated. Use the login below to sign in — handy if you forgot which user is the admin." />
          <div className="mt-4">
            <Label>Admin login</Label>
            <div className="mt-2 flex items-center gap-2 rounded-lg border border-border bg-background p-2.5">
              <code className="flex-1 truncate font-mono text-sm">{adminLogin || "admin"}</code>
              <Button size="sm" variant="ghost" onClick={() => copy("login", adminLogin || "admin")}>
                {copiedField === "login" ? <Check className="size-4 text-success" /> : <Copy className="size-4" />}
                {copiedField === "login" ? "Copied" : "Copy"}
              </Button>
            </div>
          </div>
          <div className="mt-4">
            <Label>New password</Label>
            <div className="mt-2 flex items-center gap-2 rounded-lg border border-border bg-background p-2.5">
              <code className="flex-1 truncate font-mono text-sm">{password}</code>
              <Button size="sm" variant="ghost" onClick={() => copy("password", password)}>
                {copiedField === "password" ? <Check className="size-4 text-success" /> : <Copy className="size-4" />}
                {copiedField === "password" ? "Copied" : "Copy"}
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
