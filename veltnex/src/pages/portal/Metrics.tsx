import { useParams } from "react-router-dom";
import { PerformanceHistory } from "@/components/PerformanceHistory";

/** Dedicated metrics view — the per-instance performance history (14 days).
 *  Identity/header is provided by the shared InstanceLayout. */
export default function Metrics() {
  const { id = "" } = useParams();
  return (
    <div>
      <PerformanceHistory instanceId={Number(id)} />
    </div>
  );
}
