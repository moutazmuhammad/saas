import * as React from "react";
import { Link } from "react-router-dom";
import { Receipt, ChevronRight, CircleDollarSign, CheckCircle2, Wallet } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { InfoCard } from "@/components/InfoCard";
import { StatusBadge } from "@/components/StatusBadge";
import { EmptyState } from "@/components/EmptyState";
import { Spinner } from "@/components/Spinner";
import { AlertBanner } from "@/components/AlertBanner";
import { PageHeader } from "@/components/PageHeader";
import { HelpHint } from "@/components/HelpHint";
import { api, ApiError, type ApiInvoice, type WalletData } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { cn } from "@/lib/utils";

function money(n: number, c = "USD") {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: c }).format(n);
}

const FILTERS = [
  { label: "All", value: "all" },
  { label: "Open", value: "open" },
  { label: "Paid", value: "paid" },
  { label: "Overdue", value: "overdue" },
] as const;

export default function Invoices() {
  const [invoices, setInvoices] = React.useState<ApiInvoice[] | null>(null);
  const [walletData, setWalletData] = React.useState<WalletData | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [filter, setFilter] = React.useState<(typeof FILTERS)[number]["value"]>("all");

  React.useEffect(() => {
    api
      .invoices()
      .then(setInvoices)
      .catch((e) => setError(e instanceof ApiError ? e.message : "Could not load invoices."));
    api.wallet().then(setWalletData).catch(() => setWalletData(null));
  }, []);

  const list = invoices ?? [];
  const filtered = filter === "all" ? list : list.filter((i) => i.status === filter);
  const outstanding = list
    .filter((i) => i.status === "open" || i.status === "overdue")
    .reduce((acc, i) => acc + i.residual, 0);
  const paid = list.filter((i) => i.status === "paid").reduce((acc, i) => acc + i.total, 0);
  const currency = list[0]?.currency || "USD";

  return (
    <div className="animate-fade-in">
      <PageHeader
        title={<>Billing<HelpHint anchor="invoice-status" className="ml-1.5" /></>}
        subtitle="Invoices and outstanding balances."
      />

      {error && <AlertBanner className="mt-6" variant="danger" title="Couldn't load invoices" description={error} />}

      {!invoices && !error ? (
        <div className="mt-20 flex justify-center">
          <Spinner size="lg" label="Loading invoices…" />
        </div>
      ) : (
        <>
          <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <InfoCard label="Outstanding" value={money(outstanding, currency)} icon={CircleDollarSign} hint={`${list.filter((i) => i.status === "open" || i.status === "overdue").length} open`} />
            <InfoCard label="Wallet balance" value={money(walletData?.balance ?? 0, walletData?.currency || currency)} icon={Wallet} hint={walletData && walletData.balance_bonus > 0 ? `${money(walletData.balance_bonus, walletData.currency)} bonus` : undefined} />
            <InfoCard label="Paid to date" value={money(paid, currency)} icon={CheckCircle2} />
            <InfoCard label="Invoices" value={list.length} icon={Receipt} />
          </div>

          <div className="mt-6 flex flex-wrap gap-2">
            {FILTERS.map((f) => (
              <button
                key={f.value}
                onClick={() => setFilter(f.value)}
                className={cn(
                  "rounded-full border px-4 py-1.5 text-sm font-medium transition-colors",
                  filter === f.value ? "border-primary bg-primary/15 text-foreground" : "border-border text-muted hover:text-foreground"
                )}
              >
                {f.label}
              </button>
            ))}
          </div>

          {filtered.length === 0 ? (
            <EmptyState className="mt-8" icon={Receipt} title="No invoices here" description="There are no invoices matching this filter." />
          ) : (
            <Card className="mt-6 overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted">
                      <th className="px-5 py-3 font-medium">Invoice</th>
                      <th className="hidden px-5 py-3 font-medium sm:table-cell">Instance</th>
                      <th className="hidden px-5 py-3 font-medium md:table-cell">Issued</th>
                      <th className="px-5 py-3 font-medium">Status</th>
                      <th className="px-5 py-3 text-right font-medium">Amount</th>
                      <th className="px-5 py-3" />
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {filtered.map((inv) => (
                      <tr key={inv.id} className="group transition-colors hover:bg-card/60">
                        <td className="px-5 py-4">
                          <Link to={`/my/billing/${inv.id}`} className="font-medium hover:text-primary-glow">
                            {inv.number}
                          </Link>
                        </td>
                        <td className="hidden px-5 py-4 text-muted sm:table-cell">{inv.instance_name || "—"}</td>
                        <td className="hidden px-5 py-4 text-muted md:table-cell">{inv.issued ? formatDate(inv.issued) : "—"}</td>
                        <td className="px-5 py-4"><StatusBadge status={inv.status} /></td>
                        <td className="px-5 py-4 text-right font-medium tabular-nums">{money(inv.total, inv.currency)}</td>
                        <td className="px-5 py-4 text-right">
                          <div className="flex items-center justify-end gap-2">
                            {inv.payable && inv.portal_url && (
                              <Button size="sm" onClick={() => (window.location.href = inv.portal_url)}>
                                Pay
                              </Button>
                            )}
                            <Link to={`/my/billing/${inv.id}`} className="inline-flex text-muted transition-colors hover:text-foreground" aria-label="View invoice">
                              <ChevronRight className="size-4" />
                            </Link>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
