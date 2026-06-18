import { useParams } from "react-router-dom";
import { useInstances } from "@/context/InstancesContext";
import { PageHeader } from "@/components/PageHeader";
import { envCrumbs } from "@/components/layout/PortalLayout";
import ShellConsole from "./ShellConsole";

/** Standalone Shell page (was only reachable inside the Environments workspace). */
export default function ShellPage() {
  const { id = "" } = useParams();
  const instanceId = Number(id);
  const inst = useInstances().getInstance(instanceId) ?? null;
  return (
    <div>
      <PageHeader
        breadcrumb={envCrumbs(inst, "Shell", id)}
        title="Shell"
        subtitle="Run shell commands inside your instance's container."
      />
      <ShellConsole instanceId={instanceId} />
    </div>
  );
}
