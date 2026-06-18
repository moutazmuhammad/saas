import { useParams } from "react-router-dom";
import { useInstances } from "@/context/InstancesContext";
import { PageHeader } from "@/components/PageHeader";
import { envCrumbs } from "@/components/layout/PortalLayout";
import SqlConsole from "./SqlConsole";

/** Standalone SQL console page (was only reachable inside Environments). */
export default function SqlPage() {
  const { id = "" } = useParams();
  const instanceId = Number(id);
  const inst = useInstances().getInstance(instanceId) ?? null;
  return (
    <div>
      <PageHeader
        breadcrumb={envCrumbs(inst, "SQL console", id)}
        title="SQL console"
        subtitle="Run read-only SQL queries against your databases."
      />
      <SqlConsole instanceId={instanceId} />
    </div>
  );
}
