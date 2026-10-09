import { BadgeCheck, CalendarDays, CircleHelp, ListTodo, NotebookPen, Sparkles } from "lucide-react";
import { WORKFLOW_STATUS, changedItems, formatRange, splitInfluences, stepCounts } from "../lib/format";
import StatusBadge from "./StatusBadge";
import { Button, Card, Notice } from "./ui";

function FoundList({ icon: Icon, title, items, empty }) {
  return (
    <div>
      <h3 className="flex items-center gap-2 text-sm font-medium text-ink">
        <Icon className="h-4 w-4 text-sky-300" aria-hidden="true" /> {title}
      </h3>
      {items.length ? (
        <ul className="mt-2 space-y-1.5">
          {items.slice(0, 8).map((it, i) => (
            <li key={i} className="rounded-lg border border-line bg-canvas px-3 py-2 text-sm">
              <p className="break-words text-ink">{it.title}</p>
              {it.detail && <p className="text-xs text-ink-muted">{it.detail}</p>}
            </li>
          ))}
          {items.length > 8 && <li className="text-xs text-ink-faint">+ {items.length - 8} more</li>}
        </ul>
      ) : (
        <p className="mt-1.5 text-sm text-ink-muted">{empty}</p>
      )}
    </div>
  );
}

/** Data returned by completed read steps (e.g. "Show my tasks"). */
function readFindings(workflow) {
  const out = [];
  const changedSomething = (workflow?.steps || []).some((s) => s.kind === "write" && s.status === "completed");
  for (const s of workflow?.steps || []) {
    if (s.kind !== "read" || s.status !== "completed" || !s.result) continue;
    if (s.tool === "get_tasks") {
      out.push({ key: s.step_id, icon: ListTodo, title: changedSomething ? "Your tasks before these changes" : "Your tasks", empty: "No tasks.", items: (s.result.tasks || []).map((t) => ({ title: t.title, detail: `${t.status.replace("_", " ")} · ${t.priority} priority` })) });
    } else if (s.tool === "get_schedule") {
      out.push({ key: s.step_id, icon: CalendarDays, title: changedSomething ? "Your schedule before these changes" : "Your schedule", empty: "Nothing was scheduled.", items: (s.result.events || []).map((e) => ({ title: e.title, detail: formatRange(e.start_time, e.end_time) })) });
    } else if (s.tool === "get_notes" || s.tool === "search_notes") {
      out.push({ key: s.step_id, icon: NotebookPen, title: "Notes found", empty: "No matching notes.", items: (s.result.notes || []).map((n) => ({ title: n.title, detail: n.content?.slice(0, 120) })) });
    } else if (s.tool === "check_schedule_conflict" && s.result.has_conflict) {
      out.push({ key: s.step_id, icon: CalendarDays, title: "Already booked at that time", empty: "", items: (s.result.conflicting_events || []).map((e) => ({ title: e.title, detail: formatRange(e.start_time, e.end_time) })) });
    }
  }
  return out;
}

export function AgentResult({ executionResult, onEditGoal }) {
  const wf = executionResult?.workflow;
  const status = wf?.status || executionResult?.status;
  const meta = WORKFLOW_STATUS[status] || WORKFLOW_STATUS.planned;
  const { text: summary, influences } = splitInfluences(executionResult?.plan?.summary || "");
  const changed = changedItems(wf);
  const counts = stepCounts(wf);
  const findings = readFindings(wf);
  const clarification = status === "needs_clarification";

  return (
    <Card className="p-4 sm:p-5" aria-labelledby="outcome-heading">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <h2 id="outcome-heading" className="text-base font-semibold tracking-tight text-ink">
          {meta.headline}
        </h2>
        <StatusBadge status={status} scope="workflow" />
      </div>

      {clarification ? (
        <div className="mt-3 space-y-3">
          <Notice tone="info" title="CampusPilot needs one more detail">
            {executionResult.clarification_question || "Please add the subject, date, or time to your goal."}
          </Notice>
          <Button variant="secondary" icon={CircleHelp} onClick={onEditGoal} className="w-full sm:w-auto">
            Add the detail to my goal
          </Button>
        </div>
      ) : (
        <>
          {summary && <p className="mt-2 break-words text-sm leading-relaxed text-ink-muted">{summary}</p>}
          {wf?.next_action && <p className="mt-2 text-sm font-medium text-ink">{wf.next_action}</p>}
        </>
      )}

      {executionResult?.planner_note && (
        <Notice tone="info" className="mt-3" title="Built-in planner used">
          {executionResult.planner_note}
        </Notice>
      )}

      {influences.length > 0 && (
        <div className="mt-3 rounded-xl border border-accent/30 bg-accent/5 p-3">
          <p className="flex items-center gap-2 text-sm font-medium text-ink">
            <Sparkles className="h-4 w-4 text-accent" aria-hidden="true" /> Your saved preferences shaped this plan
          </p>
          <ul className="mt-1.5 list-disc space-y-0.5 pl-5 text-sm text-ink-muted">
            {influences.map((inf) => (
              <li key={inf}>{inf}</li>
            ))}
          </ul>
        </div>
      )}

      {changed.length > 0 && (
        <div className="mt-4">
          <h3 className="text-sm font-medium text-ink">What was saved</h3>
          <ul className="mt-2 space-y-1.5">
            {changed.map((c, i) => (
              <li key={i} className="flex items-start gap-2.5 rounded-lg border border-emerald-500/25 bg-emerald-500/5 px-3 py-2 text-sm">
                <BadgeCheck className="mt-0.5 h-4 w-4 shrink-0 text-emerald-300" aria-hidden="true" />
                <div className="min-w-0">
                  <p className="break-words text-ink">{c.title}</p>
                  <p className="text-xs text-ink-muted">
                    {c.detail && `${c.detail} · `}
                    {c.verified ? "read back and verified" : "saved"}
                  </p>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

      {(counts.failed > 0 || counts.blocked > 0) && (
        <Notice tone="danger" className="mt-3" title={`${counts.failed + counts.blocked} step(s) did not complete`}>
          Failed changes were not retried automatically, so nothing was duplicated. See the steps below for details.
        </Notice>
      )}

      {findings.length > 0 && (
        <div className="mt-4 space-y-4 border-t border-line pt-4">
          {findings.map(({ key, ...f }) => (
            <FoundList key={key} {...f} />
          ))}
        </div>
      )}
    </Card>
  );
}

export default AgentResult;
