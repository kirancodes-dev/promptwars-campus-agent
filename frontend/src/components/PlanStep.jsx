import { BadgeCheck, ChevronRight, Lock } from "lucide-react";
import { KIND_LABEL, toolLabel } from "../lib/format";
import StatusBadge from "./StatusBadge";
import { cx } from "../lib/classes";

const KIND_STYLE = {
  read: "text-sky-300",
  write: "text-amber-300",
  reasoning: "text-ink-faint",
};

export function PlanStep({ step, index, isLast }) {
  const failed = step.status === "failed" || step.status === "blocked";
  const verified = step.verification?.checked && step.verification?.passed;
  const hasTech = Boolean(step.tool);

  return (
    <li className="relative flex gap-3 pb-4 last:pb-0">
      {!isLast && <span className="absolute left-[15px] top-9 bottom-0 w-px bg-line" aria-hidden="true" />}
      <span
        className={cx(
          "relative z-10 flex h-8 w-8 shrink-0 items-center justify-center rounded-full border text-xs font-semibold tabular-nums",
          step.status === "completed" ? "border-emerald-500/50 bg-emerald-500/15 text-emerald-200" : failed ? "border-rose-500/50 bg-rose-500/15 text-rose-200" : step.status === "waiting_approval" ? "border-amber-500/50 bg-amber-500/10 text-amber-200" : "border-line-strong bg-raised text-ink-muted",
        )}
        aria-hidden="true"
      >
        {index + 1}
      </span>

      <div className="min-w-0 flex-1 rounded-xl border border-line bg-canvas p-3">
        <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-2">
          <h3 className="min-w-0 break-words text-sm font-medium text-ink">
            <span className="sr-only">Step {index + 1}: </span>
            {step.title}
          </h3>
          <StatusBadge status={step.status} />
        </div>

        {step.description && <p className="mt-1 break-words text-sm leading-relaxed text-ink-muted">{step.description}</p>}

        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
          <span className={KIND_STYLE[step.kind] || "text-ink-faint"}>
            {step.kind === "write" && <Lock className="mr-1 inline h-3 w-3 align-[-1px]" aria-hidden="true" />}
            {KIND_LABEL[step.kind] || "Step"}
            {step.tool && <span className="text-ink-faint"> · {toolLabel(step.tool)}</span>}
          </span>
          {verified && (
            <span className="inline-flex items-center gap-1 text-emerald-300">
              <BadgeCheck className="h-3.5 w-3.5" aria-hidden="true" /> Saved and verified
            </span>
          )}
          {step.attempts > 1 && <span className="text-ink-faint">Tried {step.attempts} times</span>}
        </div>

        {failed && step.error && (
          <p className="mt-2 break-words rounded-lg border border-rose-500/30 bg-rose-500/10 px-2.5 py-2 text-xs leading-relaxed text-rose-200">
            {step.error}
          </p>
        )}

        {hasTech && (
          <details className="group mt-2">
            <summary className="inline-flex min-h-11 cursor-pointer items-center gap-1 rounded text-xs text-ink-faint hover:text-ink-muted">
              <ChevronRight className="h-3.5 w-3.5 transition-transform group-open:rotate-90" aria-hidden="true" />
              Technical details
            </summary>
            <dl className="mt-2 space-y-1 rounded-lg border border-line bg-surface p-2.5 font-mono text-[11px] leading-relaxed text-ink-muted">
              <div className="flex gap-2"><dt className="text-ink-faint">tool</dt><dd className="break-all">{step.tool}</dd></div>
              <div className="flex gap-2"><dt className="text-ink-faint">step</dt><dd className="break-all">{step.step_id}</dd></div>
              {step.depends_on?.length > 0 && (
                <div className="flex gap-2"><dt className="text-ink-faint">after</dt><dd className="break-all">{step.depends_on.join(", ")}</dd></div>
              )}
              <div>
                <dt className="text-ink-faint">parameters</dt>
                <dd className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap break-all">{JSON.stringify(step.parameters || {}, null, 2)}</dd>
              </div>
            </dl>
          </details>
        )}
      </div>
    </li>
  );
}

export default PlanStep;
