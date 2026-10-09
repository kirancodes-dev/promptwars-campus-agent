import { useEffect, useState } from "react";
import { CalendarPlus, Check, ListTodo, NotebookPen, Settings2, ShieldCheck, Trash2, X } from "lucide-react";
import { minutesUntil } from "../lib/format";
import { Button, Card, Notice } from "./ui";

function iconFor(tool = "") {
  if (tool.startsWith("delete") || tool.startsWith("reset")) return Trash2;
  if (tool.includes("schedule")) return CalendarPlus;
  if (tool.includes("task")) return ListTodo;
  if (tool.includes("note")) return NotebookPen;
  return Settings2;
}

function useMinutesLeft(expiresAt) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 30000);
    return () => clearInterval(t);
  }, []);
  return expiresAt ? minutesUntil(expiresAt, now) : null;
}

/**
 * Lists every data-changing action exactly as the server staged it.
 * Approve / Reject are disabled while a decision is in flight (no double submits).
 */
export function ApprovalCard({ requests = [], expiresAt, onApprove, onReject, busy, error }) {
  const minutesLeft = useMinutesLeft(expiresAt);
  const destructive = requests.some((r) => /^(delete|reset)/.test(r.tool_name));
  const n = requests.length;

  return (
    <Card className="border-amber-500/40 p-4 sm:p-5" aria-labelledby="approval-heading">
      <div className="flex items-start gap-3">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-amber-500/40 bg-amber-500/10 text-amber-300" aria-hidden="true">
          <ShieldCheck className="h-[18px] w-[18px]" />
        </span>
        <div className="min-w-0">
          <h2 id="approval-heading" className="text-base font-semibold tracking-tight text-ink">
            Review {n === 1 ? "this change" : `these ${n} changes`} before anything is saved
          </h2>
          <p className="mt-0.5 text-sm text-ink-muted">
            CampusPilot has only read your data so far. Approving saves exactly the items below.
          </p>
        </div>
      </div>

      <ul className="mt-4 space-y-2" aria-label="Proposed changes">
        {requests.map((r) => {
          const Icon = iconFor(r.tool_name);
          return (
            <li key={r.approval_id} className="flex items-start gap-3 rounded-xl border border-line bg-canvas p-3">
              <Icon className="mt-0.5 h-4 w-4 shrink-0 text-amber-300" aria-hidden="true" />
              <div className="min-w-0 text-sm">
                <p className="break-words font-medium text-ink">{r.action}</p>
                {r.description && <p className="mt-0.5 break-words text-ink-muted">{r.description}</p>}
              </div>
            </li>
          );
        })}
      </ul>

      <div className="mt-3 space-y-1 text-xs text-ink-faint">
        {destructive && <p className="font-medium text-rose-300">Includes a deletion or reset, which cannot be undone.</p>}
        <p>Existing events are never moved or overwritten.{minutesLeft !== null && ` This approval expires in ${minutesLeft} min.`}</p>
      </div>

      {error && (
        <Notice tone="danger" className="mt-3" role="alert" title="Your decision was not applied">
          {error}
        </Notice>
      )}

      <div className="sticky bottom-[calc(4.75rem+env(safe-area-inset-bottom))] -mx-4 mt-4 flex gap-2 border-t border-line bg-surface/95 px-4 py-3 backdrop-blur sm:static sm:mx-0 sm:justify-end sm:border-0 sm:bg-transparent sm:p-0 lg:bottom-0">
        <Button variant="secondary" icon={X} onClick={onReject} disabled={Boolean(busy)} loading={busy === "reject"} className="flex-1 sm:flex-none">
          Reject {n === 1 ? "change" : "all"}
        </Button>
        <Button variant="approve" icon={Check} onClick={onApprove} disabled={Boolean(busy)} loading={busy === "approve"} className="flex-[1.4] sm:flex-none">
          {busy === "approve" ? "Saving…" : `Approve ${n === 1 ? "change" : `${n} changes`}`}
        </Button>
      </div>
    </Card>
  );
}

export default ApprovalCard;
