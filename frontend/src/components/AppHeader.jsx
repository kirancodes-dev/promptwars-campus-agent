import { useId, useState } from "react";
import { ChevronDown, Cpu, Database, RefreshCw, ShieldCheck } from "lucide-react";
import { cx } from "../lib/classes";

function Brand() {
  return (
    <div className="flex min-w-0 items-center gap-2.5">
      <svg viewBox="0 0 64 64" className="h-8 w-8 shrink-0" aria-hidden="true">
        <rect width="64" height="64" rx="16" fill="#181c26" />
        <path d="M18 40.5 32 16l14 24.5-14-6.2-14 6.2Z" fill="#8b9bff" />
        <path d="m32 34.3 14 6.2L32 48l-14-7.5 14-6.2Z" fill="#34d399" />
      </svg>
      <div className="min-w-0 leading-tight">
        <h1 className="truncate text-[15px] font-semibold tracking-tight text-ink">CampusPilot AI</h1>
        <p className="hidden truncate text-xs text-ink-faint sm:block">Plans your study time. Changes nothing without you.</p>
      </div>
    </div>
  );
}

function overall(status) {
  if (!status) return { label: "Connecting…", dot: "bg-ink-faint" };
  if (status.status === "offline") return { label: "Offline", dot: "bg-rose-400" };
  if (!status.persistence_durable) return { label: status.ai_available ? "AI · demo storage" : "Demo mode", dot: "bg-amber-400" };
  return { label: status.ai_available ? "AI · saved" : "Saved", dot: "bg-emerald-400" };
}

function StatusRow({ icon: Icon, title, value, detail, tone }) {
  return (
    <li className="flex items-start gap-3 py-3 first:pt-0 last:pb-0">
      <Icon className={cx("mt-0.5 h-4 w-4 shrink-0", tone)} aria-hidden="true" />
      <div className="min-w-0">
        <p className="text-sm font-medium text-ink">
          {title}: <span className={tone}>{value}</span>
        </p>
        <p className="mt-0.5 text-xs leading-relaxed text-ink-muted">{detail}</p>
      </div>
    </li>
  );
}

export function AppHeader({ agentStatus, onRefreshStatus }) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const o = overall(agentStatus);
  const offline = agentStatus?.status === "offline";

  return (
    <header className="sticky top-0 z-30 border-b border-line bg-canvas/95 backdrop-blur supports-[backdrop-filter]:bg-canvas/80">
      <div className="mx-auto flex h-14 max-w-6xl items-center justify-between gap-3 px-4 sm:px-6">
        <Brand />
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          aria-controls={panelId}
          className="inline-flex min-h-11 shrink-0 items-center gap-2 rounded-xl border border-line bg-surface px-3 text-xs font-medium text-ink-muted hover:text-ink"
        >
          <span className={cx("h-2 w-2 rounded-full", o.dot)} aria-hidden="true" />
          <span className="hidden min-[360px]:inline">{o.label}</span>
          <span className="sr-only min-[360px]:hidden">{o.label}</span>
          <ChevronDown className={cx("h-3.5 w-3.5 transition-transform", open && "rotate-180")} aria-hidden="true" />
          <span className="sr-only">— show system status</span>
        </button>
      </div>

      {open && (
        <div id={panelId} className="border-t border-line bg-surface">
          <div className="mx-auto max-w-6xl px-4 py-4 sm:px-6">
            {offline ? (
              <p className="text-sm text-rose-200">
                CampusPilot's server can't be reached. Start the backend (see README) or check your connection.
              </p>
            ) : (
              <ul className="divide-y divide-line">
                <StatusRow
                  icon={Cpu}
                  title="Planner"
                  value={agentStatus?.ai_available ? "Gemini AI" : "Built-in planner"}
                  detail={agentStatus?.ai_message || "Checking…"}
                  tone={agentStatus?.ai_available ? "text-emerald-300" : "text-sky-300"}
                />
                <StatusRow
                  icon={Database}
                  title="Storage"
                  value={agentStatus?.persistence_durable ? "Durable (Firestore)" : "Temporary"}
                  detail={agentStatus?.persistence_message || "Checking…"}
                  tone={agentStatus?.persistence_durable ? "text-emerald-300" : "text-amber-300"}
                />
                <StatusRow
                  icon={ShieldCheck}
                  title="Privacy"
                  value={agentStatus?.identity_mode === "demo" ? "Shared demo user" : "Private session"}
                  detail={agentStatus?.identity_message || "Checking…"}
                  tone={agentStatus?.identity_mode === "demo" ? "text-amber-300" : "text-emerald-300"}
                />
              </ul>
            )}
            <button
              type="button"
              onClick={onRefreshStatus}
              className="mt-3 inline-flex min-h-11 items-center gap-2 rounded-lg px-2 text-xs font-medium text-ink-muted hover:text-ink"
            >
              <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" /> Refresh status
            </button>
          </div>
        </div>
      )}
    </header>
  );
}

export default AppHeader;
