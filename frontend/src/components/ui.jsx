import { CircleAlert, CircleCheck, Info, LoaderCircle, TriangleAlert } from "lucide-react";
import { TONE, cx } from "../lib/classes";

const NOTICE_ICON = {
  neutral: Info,
  info: Info,
  success: CircleCheck,
  warning: TriangleAlert,
  danger: CircleAlert,
};

export function Card({ as: Tag = "section", className, children, ...rest }) {
  return (
    <Tag className={cx("rounded-2xl border border-line bg-surface", className)} {...rest}>
      {children}
    </Tag>
  );
}

export function SectionTitle({ id, icon: Icon, title, subtitle, action }) {
  return (
    <div className="flex items-start justify-between gap-3">
      <div className="flex min-w-0 items-start gap-3">
        {Icon && (
          <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-line bg-raised text-accent" aria-hidden="true">
            <Icon className="h-[18px] w-[18px]" />
          </span>
        )}
        <div className="min-w-0">
          <h2 id={id} className="text-base font-semibold tracking-tight text-ink">
            {title}
          </h2>
          {subtitle && <p className="mt-0.5 text-sm text-ink-muted">{subtitle}</p>}
        </div>
      </div>
      {action}
    </div>
  );
}

const BUTTON_VARIANT = {
  primary: "bg-accent-strong text-white hover:bg-accent-hover disabled:bg-raised disabled:text-ink-faint",
  approve: "bg-emerald-700 text-white hover:bg-emerald-800 disabled:bg-raised disabled:text-ink-faint",
  secondary: "border border-line-strong bg-raised text-ink hover:border-ink-faint disabled:text-ink-faint",
  ghost: "text-ink-muted hover:bg-raised hover:text-ink disabled:text-ink-faint",
  danger: "border border-rose-500/40 bg-rose-500/10 text-rose-100 hover:bg-rose-500/20 disabled:text-ink-faint",
};

export function Button({ variant = "secondary", loading = false, icon: Icon, className, children, disabled, ...rest }) {
  return (
    <button
      type="button"
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cx(
        "inline-flex min-h-11 items-center justify-center gap-2 rounded-xl px-4 text-sm font-medium transition-colors disabled:cursor-not-allowed",
        BUTTON_VARIANT[variant],
        className,
      )}
      {...rest}
    >
      {loading ? (
        <LoaderCircle className="h-4 w-4 motion-safe:animate-spin" aria-hidden="true" />
      ) : (
        Icon && <Icon className="h-4 w-4" aria-hidden="true" />
      )}
      {children}
    </button>
  );
}

export function Notice({ tone = "info", title, children, action, className, role }) {
  const Icon = NOTICE_ICON[tone] || Info;
  return (
    <div role={role} className={cx("flex items-start gap-3 rounded-xl border p-3.5 text-sm", TONE[tone], className)}>
      <Icon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
      <div className="min-w-0 flex-1 break-words">
        {title && <p className="font-semibold text-ink">{title}</p>}
        {children && <div className={cx(title && "mt-0.5", "leading-relaxed opacity-95")}>{children}</div>}
        {action && <div className="mt-2.5">{action}</div>}
      </div>
    </div>
  );
}

export function Chip({ tone = "neutral", icon: Icon, children, className }) {
  return (
    <span className={cx("inline-flex max-w-full items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium", TONE[tone], className)}>
      {Icon && <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />}
      <span className="truncate">{children}</span>
    </span>
  );
}
