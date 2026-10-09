import { ChevronRight } from "lucide-react";
import { relativeTime, stepCounts } from "../lib/format";
import StatusBadge from "./StatusBadge";

export function ActivityItem({ workflow }) {
  const counts = stepCounts(workflow);
  const toolSteps = (workflow.steps || []).filter((s) => s.tool);
  return (
    <li className="rounded-xl border border-line bg-canvas">
      <details className="group">
        <summary className="flex min-h-11 cursor-pointer items-start gap-3 p-3">
          <ChevronRight className="mt-1 h-4 w-4 shrink-0 text-ink-faint transition-transform group-open:rotate-90" aria-hidden="true" />
          <div className="min-w-0 flex-1">
            <p className="line-clamp-2 break-words text-sm text-ink">{workflow.goal}</p>
            <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-xs text-ink-faint">
              <StatusBadge status={workflow.status} scope="workflow" />
              <time dateTime={workflow.updated_at}>{relativeTime(workflow.updated_at)}</time>
              <span>
                {counts.completed}/{toolSteps.length} actions done
              </span>
            </div>
          </div>
        </summary>
        <ol className="space-y-1.5 border-t border-line px-3 py-3">
          {(workflow.steps || []).map((s, i) => (
            <li key={s.step_id || i} className="flex flex-wrap items-center justify-between gap-2 text-sm">
              <span className="min-w-0 break-words text-ink-muted">
                {i + 1}. {s.title}
              </span>
              <StatusBadge status={s.status} />
            </li>
          ))}
          {workflow.next_action && <li className="pt-1 text-xs text-ink-faint">{workflow.next_action}</li>}
        </ol>
      </details>
    </li>
  );
}

export default ActivityItem;
