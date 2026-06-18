import * as React from "react";
import { Activity } from "lucide-react";
import { api, type MetricsHistory, type MetricSample } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

const RANGES: { key: string; label: string }[] = [
  { key: "1h", label: "1h" },
  { key: "6h", label: "6h" },
  { key: "24h", label: "24h" },
  { key: "7d", label: "7d" },
  { key: "14d", label: "14d" },
];

/**
 * Odoo.sh-style per-customer performance history: CPU / RAM (% of plan) and
 * storage over a selectable window, up to the 14-day retention. Data comes from
 * the tenant-isolated /metrics/history endpoint (only the owner's instance).
 * Dependency-free SVG charts so the bundle stays lean.
 */
export function PerformanceHistory({
  instanceId,
  accessToken,
}: {
  instanceId: number;
  accessToken?: string;
}) {
  const [range, setRange] = React.useState("24h");
  const [data, setData] = React.useState<MetricsHistory | null>(null);
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    let alive = true;
    setLoading(true);
    api
      .instanceMetricsHistory(instanceId, range, accessToken)
      .then((d) => alive && setData(d))
      .catch(() => alive && setData(null))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [instanceId, range, accessToken]);

  const samples = data?.samples ?? [];

  return (
    <Card className="p-5">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-sm font-semibold">
          <Activity className="size-4 text-primary" />
          Performance history
          <span className="text-xs font-normal text-muted">
            · retained {data?.retention_days ?? 14} days
          </span>
        </div>
        <div className="inline-flex rounded-lg border border-border bg-background p-0.5">
          {RANGES.map((r) => (
            <button
              key={r.key}
              onClick={() => setRange(r.key)}
              className={cn(
                "rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
                range === r.key
                  ? "bg-card text-foreground shadow-sm"
                  : "text-muted hover:text-foreground",
              )}
            >
              {r.label}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <div className="mt-6 h-48 animate-pulse rounded-lg bg-background" />
      ) : samples.length < 2 ? (
        <div className="mt-6 flex h-48 flex-col items-center justify-center gap-1 text-sm text-muted">
          <Activity className="size-6 opacity-40" />
          No performance data yet for this window.
          <span className="text-xs">Samples are recorded every few minutes.</span>
        </div>
      ) : (
        <div className="mt-4 grid gap-5">
          <AreaChart
            label="CPU"
            unit="% of plan"
            color="var(--primary)"
            samples={samples}
            pick={(s) => s.cpu}
            scaleMax={100}
          />
          <AreaChart
            label="Memory"
            unit="% of plan"
            color="#a142f4"
            samples={samples}
            pick={(s) => s.ram}
            scaleMax={100}
          />
          <AreaChart
            label="Storage"
            unit="MB"
            color="#12b886"
            samples={samples}
            pick={(s) => s.storage_mb}
          />
        </div>
      )}
    </Card>
  );
}

function AreaChart({
  label,
  unit,
  color,
  samples,
  pick,
  scaleMax,
}: {
  label: string;
  unit: string;
  color: string;
  samples: MetricSample[];
  pick: (s: MetricSample) => number;
  scaleMax?: number;
}) {
  const W = 600;
  const H = 120;
  const PAD = 4;
  const values = samples.map(pick);
  const dataMax = Math.max(...values, scaleMax ?? 0, 1);
  const max = scaleMax ? Math.max(scaleMax, dataMax) : dataMax * 1.15;
  const [hover, setHover] = React.useState<number | null>(null);

  const x = (i: number) =>
    samples.length > 1 ? (i / (samples.length - 1)) * (W - PAD * 2) + PAD : PAD;
  const y = (v: number) => H - PAD - (Math.min(v, max) / max) * (H - PAD * 2);

  const line = values.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const area = `${PAD},${H - PAD} ${line} ${(W - PAD).toFixed(1)},${H - PAD}`;
  const gid = `grad-${label}`;

  const last = values[values.length - 1] ?? 0;
  const peak = Math.max(...values);
  const fmt = (v: number) => (unit === "MB" ? `${v.toFixed(0)} MB` : `${v.toFixed(0)}%`);

  const hv = hover != null ? values[hover] : null;
  const ht = hover != null ? samples[hover].t : null;

  return (
    <div>
      <div className="mb-1.5 flex items-baseline justify-between text-xs">
        <span className="font-medium text-foreground">{label}</span>
        <span className="text-muted">
          now <span className="font-semibold tabular-nums text-foreground">{fmt(last)}</span>
          <span className="mx-1.5 opacity-40">·</span>peak{" "}
          <span className="tabular-nums">{fmt(peak)}</span>
          <span className="ml-1 opacity-60">{unit !== "MB" ? "" : ""}</span>
        </span>
      </div>
      <div className="relative">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          preserveAspectRatio="none"
          className="h-28 w-full rounded-lg bg-background"
          onMouseLeave={() => setHover(null)}
          onMouseMove={(e) => {
            const r = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
            const rel = ((e.clientX - r.left) / r.width) * (W - PAD * 2);
            const i = Math.round((rel / (W - PAD * 2)) * (samples.length - 1));
            setHover(Math.max(0, Math.min(samples.length - 1, i)));
          }}
        >
          <defs>
            <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity="0.28" />
              <stop offset="100%" stopColor={color} stopOpacity="0.02" />
            </linearGradient>
          </defs>
          {[0.25, 0.5, 0.75].map((g) => (
            <line
              key={g}
              x1={PAD}
              x2={W - PAD}
              y1={H * g}
              y2={H * g}
              stroke="currentColor"
              className="text-border"
              strokeWidth="0.5"
              strokeDasharray="3 3"
            />
          ))}
          <polygon points={area} fill={`url(#${gid})`} />
          <polyline
            points={line}
            fill="none"
            stroke={color}
            strokeWidth="1.5"
            vectorEffect="non-scaling-stroke"
          />
          {hover != null && (
            <line
              x1={x(hover)}
              x2={x(hover)}
              y1={PAD}
              y2={H - PAD}
              stroke={color}
              strokeWidth="1"
              vectorEffect="non-scaling-stroke"
              opacity="0.5"
            />
          )}
          {hover != null && (
            <circle cx={x(hover)} cy={y(values[hover])} r="2.5" fill={color} vectorEffect="non-scaling-stroke" />
          )}
        </svg>
        {hv != null && ht && (
          <div
            className="pointer-events-none absolute -top-1 z-10 -translate-x-1/2 -translate-y-full whitespace-nowrap rounded-md border border-border bg-card px-2 py-1 text-[11px] shadow-lg"
            style={{ left: `${(hover! / (samples.length - 1)) * 100}%` }}
          >
            <div className="font-semibold tabular-nums">{fmt(hv)}</div>
            <div className="text-muted">{formatTime(ht)}</div>
          </div>
        )}
      </div>
    </div>
  );
}

function formatTime(iso: string): string {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
