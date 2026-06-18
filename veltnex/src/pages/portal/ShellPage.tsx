import { useParams } from "react-router-dom";
import ShellConsole from "./ShellConsole";

/** Standalone Shell page. Identity/header is provided by InstanceLayout. */
export default function ShellPage() {
  const { id = "" } = useParams();
  return (
    <div>
      <ShellConsole instanceId={Number(id)} />
    </div>
  );
}
