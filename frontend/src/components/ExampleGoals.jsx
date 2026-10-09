import { Sparkles } from "lucide-react";
import { DEFAULT_EXAMPLE_GOALS } from "../lib/examples";

/** Fills the goal box only. Nothing is submitted until the student presses Plan it. */
export function ExampleGoals({ onSelect, disabled }) {
  return (
    <div>
      <p className="mb-2 text-xs font-medium text-ink-faint" id="examples-label">
        Try an example (fills the box — you still press Plan it)
      </p>
      <div className="-mx-1 flex flex-wrap gap-2 px-1" role="group" aria-labelledby="examples-label">
        {DEFAULT_EXAMPLE_GOALS.map((ex) => (
          <button
            key={ex.label}
            type="button"
            disabled={disabled}
            onClick={() => onSelect(ex.goal)}
            className={
              "inline-flex min-h-11 items-center gap-1.5 rounded-xl border px-3 text-left text-sm transition-colors disabled:cursor-not-allowed disabled:opacity-50 " +
              (ex.featured
                ? "border-accent/40 bg-accent/10 text-ink hover:bg-accent/15"
                : "border-line bg-raised text-ink-muted hover:border-line-strong hover:text-ink")
            }
          >
            {ex.featured && <Sparkles className="h-3.5 w-3.5 shrink-0 text-accent" aria-hidden="true" />}
            {ex.label}
          </button>
        ))}
      </div>
    </div>
  );
}

export default ExampleGoals;
