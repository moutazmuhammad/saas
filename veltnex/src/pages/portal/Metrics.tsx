import { useParams } from "react-router-dom";
import { useInstances } from "@/context/InstancesContext";
import { PageHeader } from "@/components/PageHeader";
import { envCrumbs } from "@/components/layout/PortalLayout";
import { PerformanceHistory } from "@/components/PerformanceHistory";

/** Dedicated metrics view — the per-instance performance history (14 days). */
export default function Metrics() {
  const { id = "" } = useParams();
  const instanceId = Number(id);
  const inst = useInstances().getInstance(instanceId) ?? null;
  return (
    <div>
      <PageHeader
        breadcrumb={envCrumbs(inst, "Metrics", id)}
        title="Metrics"
        subtitle="CPU, memory and storage for this instance over time."
      />
      <PerformanceHistory instanceId={instanceId} />
    </div>
  );
}
