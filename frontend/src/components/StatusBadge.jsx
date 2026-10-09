import { Ban, CircleCheck, CircleDashed, CircleX, Clock, LoaderCircle, OctagonX, SkipForward } from "lucide-react";
import { STEP_STATUS, WORKFLOW_STATUS } from "../lib/format";
import { Chip } from "./ui";

const ICONS = {
  planned: CircleDashed,
  waiting_approval: Clock,
  running: LoaderCircle,
  completed: CircleCheck,
  failed: CircleX,
  blocked: OctagonX,
  skipped: SkipForward,
  rejected: Ban,
  partially_completed: CircleX,
  needs_clarification: Clock,
};

/** Status chip that always pairs colour with an icon and a text label. */
export function StatusBadge({ status, scope = "step", className }) {
  const meta = (scope === "workflow" ? WORKFLOW_STATUS : STEP_STATUS)[status] || { label: status, tone: "neutral" };
  return (
    <Chip tone={meta.tone} icon={ICONS[status] || CircleDashed} className={className}>
      {meta.label}
    </Chip>
  );
}

export default StatusBadge;
