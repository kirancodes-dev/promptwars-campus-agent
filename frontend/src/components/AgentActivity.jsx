import { useCallback, useEffect, useState } from "react";
import { ChevronRight, History, RefreshCw } from "lucide-react";
import { getAuditLog, getWorkflows } from "../api/agent";
import { relativeTime } from "../lib/format";
import ActivityItem from "./ActivityItem";
import { Button, Card, Notice, SectionTitle } from "./ui";

const EVENT_LABEL = {
  workflow_started: "Plan started",
  step_started: "Step started",
  step_blocked: "Step blocked by a failed prerequisite",
  approval_requested: "Approval requested",
  approval_granted: "You approved changes",
  approval_rejected: "You rejected changes",
  tool_succeeded: "Step succeeded",
  tool_failed: "Step failed",
  verification_succeeded: "Change verified",
  verification_failed: "Verification failed",
  workflow_completed: "Plan completed",
  workflow_partially_completed: "Plan partly completed",
  workflow_failed: "Plan failed",
  clarification_requested: "Asked for a detail",
  execution_summary: "Run summary",
  preferences_edited_by_user: "You edited preferences",
  preferences_reset_by_user: "You reset preferences",
};

export function AgentActivity({ refreshKey }) {
  const [workflows, setWorkflows] = useState(null);
  const [audit, setAudit] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const apply = useCallback(([wf, log]) => {
    setWorkflows(wf || []);
    setAudit(log || []);
    setError("");
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      apply(await Promise.all([getWorkflows(10), getAuditLog(40)]));
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [apply]);

  useEffect(() => {
    let ignore = false;
    Promise.all([getWorkflows(10), getAuditLog(40)])
      .then((data) => !ignore && apply(data))
      .catch((err) => !ignore && setError(err.message));
    return () => {
      ignore = true;
    };
  }, [apply, refreshKey]);

  return (
    <Card className="p-4 sm:p-5" aria-labelledby="activity-heading">
      <SectionTitle
        id="activity-heading"
        icon={History}
        title="Activity"
        subtitle="What CampusPilot planned, what you approved, and what actually happened."
        action={
          <Button variant="ghost" onClick={load} loading={loading} icon={RefreshCw} aria-label="Refresh activity" className="px-3">
            <span className="sr-only sm:not-sr-only">Refresh</span>
          </Button>
        }
      />

      {error && (
        <Notice tone="danger" className="mt-4" role="alert" title="Activity could not be loaded" action={<Button onClick={load}>Try again</Button>}>
          {error}
        </Notice>
      )}

      {workflows === null && !error ? (
        <p className="mt-4 text-sm text-ink-muted" aria-live="polite">
          Loading activity…
        </p>
      ) : workflows?.length === 0 ? (
        <p className="mt-4 rounded-xl border border-dashed border-line p-4 text-sm text-ink-muted">
          No activity yet. Plans you run will appear here with every step's outcome.
        </p>
      ) : (
        <ul className="mt-4 space-y-2">
          {workflows?.map((wf) => (
            <ActivityItem key={wf.workflow_id} workflow={wf} />
          ))}
        </ul>
      )}

      {audit.length > 0 && (
        <details className="group mt-4 border-t border-line pt-3">
          <summary className="inline-flex min-h-11 cursor-pointer items-center gap-1.5 text-sm text-ink-muted hover:text-ink">
            <ChevronRight className="h-4 w-4 transition-transform group-open:rotate-90" aria-hidden="true" />
            Detailed audit log ({audit.length})
          </summary>
          <ol className="mt-2 space-y-1">
            {audit.map((e) => (
              <li key={e.id} className="flex flex-wrap items-baseline justify-between gap-x-3 rounded-lg px-2 py-1.5 text-xs odd:bg-canvas">
                <span className="min-w-0 break-words text-ink-muted">
                  {EVENT_LABEL[e.event_type] || e.event_type}
                  {e.tool && <span className="font-mono text-ink-faint"> · {e.tool}</span>}
                  {e.error_summary && <span className="block text-rose-300">{e.error_summary}</span>}
                </span>
                <time className="shrink-0 tabular-nums text-ink-faint" dateTime={e.timestamp}>
                  {relativeTime(e.timestamp)}
                </time>
              </li>
            ))}
          </ol>
          <p className="mt-2 text-xs text-ink-faint">The audit log stores step names and outcomes only — never your parameters or credentials.</p>
        </details>
      )}
    </Card>
  );
}

export default AgentActivity;
