import * as React from "react";
import { RefreshCw, Wallet, HardDrive, CreditCard, Sparkles } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { api, type ApiInstance } from "@/lib/api";
import { useToast } from "@/context/ToastContext";

function money(amount: number, currency = "USD") {
  try {
    return new Intl.NumberFormat(undefined, { style: "currency", currency }).format(amount);
  } catch {
    return `${currency} ${amount.toFixed(2)}`;
  }
}

/**
 * Customer billing controls for one instance (A1/A2/A4):
 *  - auto-renew toggle + saved payment method,
 *  - wallet balance,
 *  - storage usage / overage estimate,
 *  - trial-conversion promo banner.
 */
export function BillingPanel({
  instance,
  onChange,
}: {
  instance: ApiInstance;
  onChange: () => void | Promise<void>;
}) {
  const toast = useToast();
  const [saving, setSaving] = React.useState(false);
  const ss = instance.storage_summary;
  const promo = instance.trial_promo;
  const method = instance.payment_method;
  const currency = ss?.currency || instance.currency || "USD";

  async function toggleAutoRenew() {
    setSaving(true);
    try {
      await api.setAutoRenew(instance.id, {
        subscription: !instance.auto_renew_subscription,
      });
      toast.success(
        "Auto-renew updated",
        !instance.auto_renew_subscription
          ? "We'll charge your saved method on renewal."
          : "Auto-renew turned off — you'll pay invoices manually.",
      );
      await onChange();
    } catch {
      toast.error("Could not update auto-renew", "Please try again.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="mt-4 grid gap-4 lg:grid-cols-3">
      {/* Auto-renew + payment method */}
      <Card className="flex flex-col gap-3 p-5">
        <div className="flex items-center gap-2 text-sm font-semibold">
          <RefreshCw className="size-4 text-primary-glow" /> Auto-renew
        </div>
        <p className="text-xs text-muted">
          {instance.auto_renew_subscription
            ? "Your subscription renews automatically on the renewal date."
            : "Auto-renew is off — invoices are issued but you pay them manually."}
        </p>
        <div className="flex items-center gap-2 text-xs text-muted">
          <CreditCard className="size-3.5" />
          {method ? (
            <span>{method.label}{method.provider ? ` · ${method.provider}` : ""}</span>
          ) : (
            <span>No saved payment method yet — added on your next payment.</span>
          )}
        </div>
        <Button
          variant={instance.auto_renew_subscription ? "secondary" : "default"}
          disabled={saving}
          onClick={toggleAutoRenew}
          className="mt-1 w-fit"
        >
          {instance.auto_renew_subscription ? "Turn off auto-renew" : "Turn on auto-renew"}
        </Button>
      </Card>

      {/* Wallet */}
      <Card className="flex flex-col gap-2 p-5">
        <div className="flex items-center gap-2 text-sm font-semibold">
          <Wallet className="size-4 text-primary-glow" /> Wallet credit
        </div>
        <p className="text-2xl font-semibold tabular-nums">
          {money(instance.wallet_balance ?? 0, currency)}
        </p>
        <p className="text-xs text-muted">
          Account credit is applied automatically to your future invoices.
          Non-refundable; usable only on the platform.
        </p>
      </Card>

      {/* Storage usage / overage */}
      <Card className="flex flex-col gap-2 p-5">
        <div className="flex items-center gap-2 text-sm font-semibold">
          <HardDrive className="size-4 text-primary-glow" /> Storage
        </div>
        {ss ? (
          <>
            <p className="text-xs text-muted">
              {ss.used_gb} GB of {ss.included_gb} GB included ({ss.usage_pct}%)
            </p>
            <div className="h-2 w-full overflow-hidden rounded-full bg-card ring-1 ring-border">
              <div
                className={`h-full rounded-full ${ss.usage_pct >= 100 ? "bg-warning" : "bg-primary"}`}
                style={{ width: `${Math.min(100, ss.usage_pct)}%` }}
              />
            </div>
            {ss.overage_blocks > 0 ? (
              <p className="text-xs text-warning">
                {ss.overage_blocks} × {ss.block_gb} GB overage block(s) —
                est. {money(ss.estimated_overage_charge, currency)} on next invoice.
                Your service keeps running.
              </p>
            ) : (
              <p className="text-xs text-muted">Within your included storage.</p>
            )}
          </>
        ) : (
          <p className="text-xs text-muted">Usage data not available yet.</p>
        )}
      </Card>

      {/* Trial promo banner */}
      {promo?.active && (
        <Card className="p-4 lg:col-span-3">
          <p className="flex items-center gap-2 text-sm text-primary-glow">
            <Sparkles className="size-4" />
            Welcome discount active: {promo.pct}% off for{" "}
            {promo.cycles_remaining} more billing cycle(s).
            {promo.total_saved > 0
              ? ` You've saved ${money(promo.total_saved, currency)} so far.`
              : ""}
          </p>
        </Card>
      )}
    </div>
  );
}
