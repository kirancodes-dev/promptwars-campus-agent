import { forwardRef, useState } from "react";
import { ArrowUp } from "lucide-react";
import { MAX_GOAL_CHARS, validateGoal } from "../lib/format";
import ExampleGoals from "./ExampleGoals";
import { cx } from "../lib/classes";
import { Button, Card } from "./ui";

export const GoalInput = forwardRef(function GoalInput({ goal, onChange, onSubmit, loading, disabled }, textareaRef) {
  const [touchedError, setTouchedError] = useState(null);
  const count = goal.length;
  const over = count > MAX_GOAL_CHARS;

  const submit = (e) => {
    e?.preventDefault();
    const err = validateGoal(goal);
    setTouchedError(err);
    if (err) {
      textareaRef?.current?.focus();
      return;
    }
    onSubmit(goal.trim());
  };

  const onKeyDown = (e) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit(e);
  };

  const error = touchedError && validateGoal(goal) ? touchedError : over ? validateGoal(goal) : null;

  return (
    <Card className="p-4 sm:p-6" aria-labelledby="goal-heading">
      <form onSubmit={submit} noValidate className="space-y-4">
        <div>
          <label id="goal-heading" htmlFor="goal-input" className="block text-lg font-semibold tracking-tight text-ink sm:text-xl">
            What do you want to get done?
          </label>
          <p id="goal-help" className="mt-1 text-sm text-ink-muted">
            Describe it in your own words — subjects, how long, and anything already booked.
          </p>
        </div>

        <div>
          <textarea
            id="goal-input"
            ref={textareaRef}
            rows={4}
            value={goal}
            onChange={(e) => {
              onChange(e.target.value);
              if (touchedError) setTouchedError(null);
            }}
            onKeyDown={onKeyDown}
            disabled={disabled || loading}
            aria-invalid={Boolean(error) || undefined}
            aria-describedby={cx("goal-help", error && "goal-error", "goal-count")}
            placeholder="e.g. I need 2 hours of DBMS and 1 hour of DAA tomorrow. I have a meeting at 4 PM."
            className={cx(
              "block w-full resize-y rounded-xl border bg-canvas px-3.5 py-3 text-base leading-relaxed text-ink placeholder:text-ink-faint focus:outline-none focus-visible:outline-2 disabled:opacity-60",
              error ? "border-rose-500/60" : "border-line-strong",
            )}
          />
          <div className="mt-1.5 flex items-start justify-between gap-3 text-xs">
            <p id="goal-error" role={error ? "alert" : undefined} className="min-h-4 text-rose-300">
              {error}
            </p>
            <p id="goal-count" className={cx("shrink-0 tabular-nums", over ? "text-rose-300" : "text-ink-faint")}>
              {count}/{MAX_GOAL_CHARS}
            </p>
          </div>
        </div>

        <ExampleGoals
          disabled={disabled || loading}
          onSelect={(text) => {
            onChange(text);
            setTouchedError(null);
            requestAnimationFrame(() => textareaRef?.current?.focus());
          }}
        />

        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-xs text-ink-faint">
            <span className="hidden sm:inline">Press Ctrl/⌘ + Enter to submit. </span>Nothing is changed until you approve it.
          </p>
          <Button type="submit" variant="primary" loading={loading} disabled={disabled} icon={ArrowUp} className="w-full shrink-0 whitespace-nowrap sm:w-auto">
            {loading ? "Planning…" : "Plan it"}
          </Button>
        </div>
      </form>
    </Card>
  );
});

export default GoalInput;
