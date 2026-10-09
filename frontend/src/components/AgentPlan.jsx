import { ListChecks } from "lucide-react";
import { toDisplaySteps } from "../lib/format";
import PlanStep from "./PlanStep";
import { Card, SectionTitle } from "./ui";

export function AgentPlan({ executionResult }) {
  const steps = toDisplaySteps(executionResult);
  if (!steps.length) return null;
  const writes = steps.filter((s) => s.kind === "write").length;
  const reads = steps.filter((s) => s.kind === "read").length;

  return (
    <Card className="p-4 sm:p-5" aria-labelledby="plan-heading">
      <SectionTitle
        id="plan-heading"
        icon={ListChecks}
        title={`The plan · ${steps.length} step${steps.length === 1 ? "" : "s"}`}
        subtitle={
          writes
            ? `${reads} step${reads === 1 ? " reads" : "s read"} your data · ${writes} would change it (approval needed)`
            : `${reads} step${reads === 1 ? " reads" : "s read"} your data · nothing will be changed`
        }
      />
      <ol className="mt-4">
        {steps.map((step, i) => (
          <PlanStep key={step.step_id || i} step={step} index={i} isLast={i === steps.length - 1} />
        ))}
      </ol>
    </Card>
  );
}

export default AgentPlan;
