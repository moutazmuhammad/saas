import { useParams } from "react-router-dom";
import { TableProperties } from "lucide-react";
import { useInstances } from "@/context/InstancesContext";
import { PortalBreadcrumb, envCrumbs } from "@/components/layout/PortalLayout";
import SqlConsole from "./SqlConsole";

/** Standalone SQL console page (was only reachable inside Environments). */
export default function SqlPage() {
  const { id = "" } = useParams();
  const instanceId = Number(id);
  const inst = useInstances().getInstance(instanceId) ?? null;
  return (
    <div>
      <PortalBreadcrumb items={envCrumbs(inst, "SQL", id)} />
      <div className="mb-6">
        <h1 className="flex items-center gap-2 text-2xl font-normal">
          <TableProperties className="size-6 text-primary" /> SQL console
        </h1>
        <p className="mt-1 text-sm text-muted">
          Run read-only SQL queries against your databases.
        </p>
      </div>
      <SqlConsole instanceId={instanceId} />
    </div>
  );
}
