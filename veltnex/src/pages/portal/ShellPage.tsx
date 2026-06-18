import { useParams } from "react-router-dom";
import { TerminalSquare } from "lucide-react";
import { useInstances } from "@/context/InstancesContext";
import { PortalBreadcrumb, envCrumbs } from "@/components/layout/PortalLayout";
import ShellConsole from "./ShellConsole";

/** Standalone Shell page (was only reachable inside the Environments workspace). */
export default function ShellPage() {
  const { id = "" } = useParams();
  const instanceId = Number(id);
  const inst = useInstances().getInstance(instanceId) ?? null;
  return (
    <div>
      <PortalBreadcrumb items={envCrumbs(inst, "Shell", id)} />
      <div className="mb-6">
        <h1 className="flex items-center gap-2 text-2xl font-normal">
          <TerminalSquare className="size-6 text-primary" /> Shell
        </h1>
        <p className="mt-1 text-sm text-muted">
          Run shell commands inside your instance's container.
        </p>
      </div>
      <ShellConsole instanceId={instanceId} />
    </div>
  );
}
