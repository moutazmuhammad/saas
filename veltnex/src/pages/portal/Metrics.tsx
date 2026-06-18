import { useParams } from "react-router-dom";
import { Activity } from "lucide-react";
import { useInstances } from "@/context/InstancesContext";
import { PortalBreadcrumb, envCrumbs } from "@/components/layout/PortalLayout";
import { PerformanceHistory } from "@/components/PerformanceHistory";

/** Dedicated metrics view — the per-instance performance history (14 days). */
export default function Metrics() {
  const { id = "" } = useParams();
  const instanceId = Number(id);
  const inst = useInstances().getInstance(instanceId) ?? null;
  return (
    <div>
      <PortalBreadcrumb items={envCrumbs(inst, "Metrics", id)} />
      <div className="mb-6">
        <h1 className="flex items-center gap-2 text-2xl font-normal">
          <Activity className="size-6 text-primary" /> Metrics
        </h1>
        <p className="mt-1 text-sm text-muted">
          CPU, memory and storage for this instance over time.
        </p>
      </div>
      <PerformanceHistory instanceId={instanceId} />
    </div>
  );
}
