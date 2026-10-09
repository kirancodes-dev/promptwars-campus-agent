export function cx(...parts) {
  return parts.filter(Boolean).join(" ");
}

export const TONE = {
  neutral: "border-line bg-raised text-ink-muted",
  info: "border-sky-500/30 bg-sky-500/10 text-sky-200",
  success: "border-emerald-500/30 bg-emerald-500/10 text-emerald-200",
  warning: "border-amber-500/35 bg-amber-500/10 text-amber-100",
  danger: "border-rose-500/35 bg-rose-500/10 text-rose-200",
};
