import { Brain, History, Sparkles } from "lucide-react";
import { cx } from "../lib/classes";

const VIEWS = [
  { id: "plan", label: "Plan", icon: Sparkles },
  { id: "activity", label: "Activity", icon: History },
  { id: "memory", label: "Preferences", icon: Brain },
];

/** Mobile-only tab bar. On large screens every panel is visible at once. */
export function BottomNav({ view, onChange, attention }) {
  return (
    <nav aria-label="Sections" className="safe-bottom fixed inset-x-0 bottom-0 z-30 border-t border-line bg-canvas/95 backdrop-blur lg:hidden">
      <ul className="mx-auto grid max-w-md grid-cols-3">
        {VIEWS.map(({ id, label, icon: Icon }) => {
          const active = view === id;
          return (
            <li key={id}>
              <button
                type="button"
                onClick={() => onChange(id)}
                aria-current={active ? "page" : undefined}
                className={cx("relative flex min-h-16 w-full flex-col items-center justify-center gap-1 text-xs font-medium", active ? "text-ink" : "text-ink-faint hover:text-ink-muted")}
              >
                <Icon className={cx("h-5 w-5", active && "text-accent")} aria-hidden="true" />
                {label}
                {attention === id && !active && (
                  <>
                    <span className="absolute right-[calc(50%-18px)] top-2.5 h-2 w-2 rounded-full bg-amber-400" aria-hidden="true" />
                    <span className="sr-only"> (needs attention)</span>
                  </>
                )}
              </button>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

export default BottomNav;
