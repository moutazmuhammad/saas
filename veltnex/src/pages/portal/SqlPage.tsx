import { useParams } from "react-router-dom";
import SqlConsole from "./SqlConsole";

/** Standalone SQL console page. Identity/header is provided by InstanceLayout. */
export default function SqlPage() {
  const { id = "" } = useParams();
  return (
    <div>
      <SqlConsole instanceId={Number(id)} />
    </div>
  );
}
