import * as React from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Play, Pause, Trash2, ArrowDownToLine } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { AlertBanner } from "@/components/AlertBanner";
import { PortalBreadcrumb, envCrumbs } from "@/components/layout/PortalLayout";
import { api, logStreamUrl, type ApiInstance } from "@/lib/api";
import { cn, makeId } from "@/lib/utils";

interface Line {
  id: string;
  text: string;
}

// Log-level colouring (Google Cloud Logging-style severities) using the
// website's theme tokens, so the pane matches the rest of the site and adapts
// to light/dark: ERROR = red, WARNING = amber, DEBUG = muted, INFO = normal.
function levelClass(text: string): string {
  if (/\bERROR\b|CRITICAL|Traceback/.test(text)) return "text-danger";
  if (/\bWARNING\b/.test(text)) return "text-warning";
  if (/\bDEBUG\b/.test(text)) return "text-muted";
  return "text-foreground";
}

export default function Logs() {
  const { id = "" } = useParams();
  const instanceId = Number(id);
  const navigate = useNavigate();

  const [instance, setInstance] = React.useState<ApiInstance | null>(null);
  const [lines, setLines] = React.useState<Line[]>([]);
  const [paused, setPaused] = React.useState(false);
  const [autoScroll, setAutoScroll] = React.useState(true);
  const [connError, setConnError] = React.useState<string | null>(null);
  const viewport = React.useRef<HTMLDivElement>(null);
  const sourceRef = React.useRef<EventSource | null>(null);

  React.useEffect(() => {
    api.instance(instanceId).then(setInstance).catch(() => {});
  }, [instanceId]);

  // Live logs are a hosting-only (self-managed) feature. Managed services
  // don't expose logs — bounce back to the instance overview.
  React.useEffect(() => {
    if (instance && !instance.is_hosting) {
      navigate(`/my/instances/${id}`, { replace: true });
    }
  }, [instance, id, navigate]);

  // Logs only stream while the instance is running. Stopped / suspended /
  // not-yet-running instances have no live container — the server rejects
  // the stream, so don't even open it; show a clear message instead.
  const logsAvailable = instance ? instance.state === "running" : true;

  // Open / close the SSE stream based on pause state.
  React.useEffect(() => {
    if (paused || (instance && instance.state !== "running")) {
      sourceRef.current?.close();
      sourceRef.current = null;
      return;
    }
    setConnError(null);
    const es = new EventSource(logStreamUrl(instanceId, 200));
    sourceRef.current = es;

    es.onmessage = (e) => {
      let text = e.data;
      try {
        text = JSON.parse(e.data);
      } catch {
        /* already plain text */
      }
      if (typeof text !== "string") text = String(text);
      setLines((prev) => [...prev.slice(-600), { id: makeId("log"), text }]);
    };
    es.addEventListener("done", () => {
      es.close();
    });
    es.onerror = () => {
      setConnError(
        "The log stream was interrupted. It will resume when the instance is running — or press Resume to retry."
      );
      es.close();
      sourceRef.current = null;
    };

    return () => {
      es.close();
      sourceRef.current = null;
    };
  }, [paused, instanceId, instance]);

  // Auto-scroll to bottom on new lines.
  React.useEffect(() => {
    if (autoScroll && viewport.current) {
      viewport.current.scrollTop = viewport.current.scrollHeight;
    }
  }, [lines, autoScroll]);

  return (
    <div className="animate-fade-in">
      <PortalBreadcrumb items={envCrumbs(instance, "Logs", id)} />

      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Logs</h1>
          <p className="mt-1 text-sm text-muted">
            Live container stream{instance ? ` · ${instance.name}` : ""}
          </p>
        </div>
        {logsAvailable && (
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" size="sm" onClick={() => setPaused((p) => !p)}>
              {paused ? <Play className="size-4" /> : <Pause className="size-4" />}
              {paused ? "Resume" : "Pause"}
            </Button>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setAutoScroll((a) => !a)}
              className={cn(autoScroll && "border-primary/40 text-primary")}
            >
              <ArrowDownToLine className="size-4" />
              Auto-scroll
            </Button>
            <Button variant="secondary" size="sm" onClick={() => setLines([])}>
              <Trash2 className="size-4" />
              Clear
            </Button>
          </div>
        )}
      </div>

      {!logsAvailable ? (
        <AlertBanner
          className="mt-6"
          variant="warning"
          title="Logs unavailable"
          description={
            instance?.state === "suspended"
              ? "This instance is suspended. Settle the outstanding invoice to view its logs."
              : instance?.state === "stopped"
                ? "This instance is stopped. Start it to view its live logs."
                : "Live logs become available once the instance is running."
          }
        />
      ) : (
      <>
      {connError && (
        <AlertBanner className="mt-6" variant="warning" title="Log stream interrupted" description={connError} onDismiss={() => setConnError(null)} />
      )}

      <Card className="mt-6 overflow-hidden">
        <div className="flex items-center justify-between border-b border-border bg-card px-4 py-2.5">
          <div className="flex items-center gap-2">
            <span className="flex gap-1.5">
              <span className="size-2.5 rounded-full bg-danger/70" />
              <span className="size-2.5 rounded-full bg-warning/70" />
              <span className="size-2.5 rounded-full bg-success/70" />
            </span>
            <span className="ml-2 font-mono text-xs text-muted">{instance?.name || "instance"} — odoo.log</span>
          </div>
          <span className="flex items-center gap-1.5 text-xs text-muted">
            <span className={cn("size-1.5 rounded-full", paused ? "bg-muted" : "bg-success animate-pulse-soft")} />
            {paused ? "Paused" : "Streaming"} · {lines.length} lines
          </span>
        </div>

        <div
          ref={viewport}
          onScroll={(e) => {
            const el = e.currentTarget;
            const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
            if (!atBottom && autoScroll) setAutoScroll(false);
          }}
          className="h-[calc(100vh-17rem)] min-h-[420px] overflow-y-auto bg-background p-4 font-mono text-xs leading-relaxed"
        >
          {lines.length === 0 ? (
            <p className="text-muted">
              {paused ? "Stream paused." : "Waiting for log output… (logs stream only while the instance is running)"}
            </p>
          ) : (
            lines.map((l) => (
              <div key={l.id} className={cn("whitespace-pre-wrap break-all py-0.5", levelClass(l.text))}>
                {l.text}
              </div>
            ))
          )}
        </div>
      </Card>
      </>
      )}
    </div>
  );
}
