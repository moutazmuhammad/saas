import * as React from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  Server,
  Receipt,
  Plus,
  ArrowRight,
  Activity,
  CircleDollarSign,
  Database,
} from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { InfoCard } from "@/components/InfoCard";
import { StatusBadge } from "@/components/StatusBadge";
import { EmptyState } from "@/components/EmptyState";
import { Spinner } from "@/components/Spinner";
import { AlertBanner } from "@/components/AlertBanner";
import { useAuth } from "@/context/AuthContext";
import { api, ApiError, type DashboardData } from "@/lib/api";
import { formatDate } from "@/lib/format";

function money(n: number, c = "USD") {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: c }).format(n);
}

export default function Dashboard() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [data, setData] = React.useState<DashboardData | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    api
      .dashboard()
      .then(setData)
      .catch((e) => setError(e instanceof ApiError ? e.message : "Could not load your dashboard."));
  }, []);

  return (
    <div className="animate-fade-in">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">
            Welcome back{user ? `, ${user.name.split(" ")[0]}` : ""}
          </h1>
          <p className="mt-1 text-sm text-muted">
            Here's what's happening across your {user?.company} workspace.
          </p>
        </div>
        <Button onClick={() => navigate("/hosting")}>
          <Plus className="size-4" />
          New instance
        </Button>
      </div>

      {error && <AlertBanner className="mt-6" variant="danger" title="Couldn't load dashboard" description={error} />}

      {!data && !error && (
        <div className="mt-20 flex justify-center">
          <Spinner size="lg" label="Loading your workspace…" />
        </div>
      )}

      {data && (
        <>
          <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <InfoCard label="Instances" value={data.stats.instances} icon={Server} hint={`${data.stats.running} running`} />
            <InfoCard label="Running" value={data.stats.running} icon={Activity} />
            <InfoCard
              label="Outstanding"
              value={money(data.stats.outstanding)}
              icon={CircleDollarSign}
              hint={`${data.stats.open_invoices} open invoice${data.stats.open_invoices === 1 ? "" : "s"}`}
            />
            <InfoCard
              label="Hosting"
              value={data.instances.filter((i) => i.is_hosting).length}
              icon={Database}
              hint="Self-managed instances"
            />
          </div>

          <div className="mt-8 grid gap-6 lg:grid-cols-3">
            <Card className="lg:col-span-2">
              <div className="flex items-center justify-between border-b border-border p-5">
                <h2 className="font-semibold">Your instances</h2>
                <Link to="/my/instances" className="inline-flex items-center gap-1 text-sm text-primary-glow hover:underline">
                  View all <ArrowRight className="size-3.5" />
                </Link>
              </div>
              {data.instances.length === 0 ? (
                <div className="p-5">
                  <EmptyState
                    icon={Server}
                    title="No instances yet"
                    description="Deploy your first Odoo instance to get started."
                    action={<Button onClick={() => navigate("/hosting")}>Create instance</Button>}
                  />
                </div>
              ) : (
                <ul className="divide-y divide-border">
                  {data.instances.slice(0, 5).map((i) => (
                    <li key={i.id}>
                      <Link
                        to={`/my/instances/${i.id}`}
                        className="flex items-center justify-between gap-4 p-5 transition-colors hover:bg-card/60"
                      >
                        <div className="min-w-0">
                          <p className="truncate font-medium">{i.name}</p>
                          <p className="truncate text-sm text-muted">{i.region || i.domain}</p>
                        </div>
                        <div className="flex items-center gap-4">
                          <span className="hidden text-sm text-muted sm:block">{i.workers} workers</span>
                          <StatusBadge status={i.state} label={i.state_label} />
                        </div>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </Card>

            <Card>
              <div className="flex items-center justify-between border-b border-border p-5">
                <h2 className="font-semibold">Recent invoices</h2>
                <Receipt className="size-4 text-muted" />
              </div>
              {data.recent_invoices.length === 0 ? (
                <div className="p-5 text-sm text-muted">No invoices yet.</div>
              ) : (
                <ul className="divide-y divide-border">
                  {data.recent_invoices.map((inv) => (
                    <li key={inv.id}>
                      <Link
                        to={`/my/billing/${inv.id}`}
                        className="flex items-center justify-between gap-3 p-5 transition-colors hover:bg-card/60"
                      >
                        <div className="min-w-0">
                          <p className="truncate text-sm font-medium">{inv.number}</p>
                          <p className="text-xs text-muted">{inv.issued ? formatDate(inv.issued) : ""}</p>
                        </div>
                        <div className="flex flex-col items-end gap-1">
                          <span className="text-sm font-medium tabular-nums">{money(inv.total, inv.currency)}</span>
                          <StatusBadge status={inv.status} />
                        </div>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </div>
        </>
      )}
    </div>
  );
}
