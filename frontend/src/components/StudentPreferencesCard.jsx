import { useCallback, useEffect, useId, useRef, useState } from "react";
import { Brain, Check, Pencil, Plus, RotateCcw, Trash2, X } from "lucide-react";
import { getStudentPreferences, resetPreferences, savePreferences } from "../api/agent";
import { cx } from "../lib/classes";
import { DAYS, TIMINGS, toForm, toUpdates, validatePreferenceForm } from "../lib/preferences";
import { Button, Card, Notice, SectionTitle } from "./ui";

function Field({ id, label, error, children, hint }) {
  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-sm font-medium text-ink">
        {label}
      </label>
      {children}
      {hint && !error && <p id={`${id}-hint`} className="mt-1 text-xs text-ink-faint">{hint}</p>}
      {error && (
        <p id={`${id}-error`} className="mt-1 text-xs text-rose-300">
          {error}
        </p>
      )}
    </div>
  );
}

const inputClass =
  "block min-h-11 w-full rounded-xl border border-line-strong bg-canvas px-3 text-base text-ink placeholder:text-ink-faint focus:outline-none focus-visible:outline-2 sm:text-sm";

function Summary({ prefs }) {
  const items = [
    ["Study window", `${prefs.preferred_study_start} – ${prefs.preferred_study_end}`],
    ["Session length", `${prefs.preferred_session_minutes} min`],
    ["Break", `${prefs.preferred_break_minutes} min`],
    ["Study days", prefs.preferred_study_days.length === 7 ? "Every day" : prefs.preferred_study_days.map((d) => d.slice(0, 3)).join(", ")],
  ];
  const timings = Object.entries(prefs.subject_time_preferences || {});
  return (
    <div className="space-y-3">
      <dl className="grid grid-cols-2 gap-2">
        {items.map(([k, v]) => (
          <div key={k} className="rounded-xl border border-line bg-canvas px-3 py-2">
            <dt className="text-xs text-ink-faint">{k}</dt>
            <dd className="mt-0.5 break-words text-sm font-medium text-ink">{v}</dd>
          </div>
        ))}
      </dl>
      <div className="text-sm">
        <p className="text-xs text-ink-faint">Subjects &amp; timing</p>
        {prefs.preferred_subjects?.length || timings.length ? (
          <ul className="mt-1.5 flex flex-wrap gap-1.5">
            {[...new Set([...(prefs.preferred_subjects || []), ...timings.map(([s]) => s)])].map((s) => (
              <li key={s} className="rounded-lg border border-line bg-raised px-2 py-1 text-xs text-ink">
                {s}
                {prefs.subject_time_preferences?.[s] && <span className="text-ink-muted"> · {prefs.subject_time_preferences[s]}</span>}
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-1 text-ink-muted">None saved yet.</p>
        )}
      </div>
      {prefs.planning_notes?.length > 0 && (
        <div className="text-sm">
          <p className="text-xs text-ink-faint">Planning notes</p>
          <ul className="mt-1 list-disc space-y-0.5 pl-5 text-ink-muted">
            {prefs.planning_notes.map((n) => (
              <li key={n} className="break-words">
                {n}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export function StudentPreferencesCard({ refreshKey, onChanged }) {
  const uid = useId();
  const [prefs, setPrefs] = useState(null);
  const [storage, setStorage] = useState({ durable: false, message: "" });
  const [loadError, setLoadError] = useState("");
  const [mode, setMode] = useState("view"); // view | edit | confirm-reset
  const [form, setForm] = useState(null);
  const [errors, setErrors] = useState({});
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState(null); // {tone, text}
  const resetHeadingRef = useRef(null);
  const editHeadingRef = useRef(null);

  const apply = useCallback((data) => {
    setPrefs(data.preferences);
    setStorage({ durable: data.durable, message: data.storage_message });
    setLoadError("");
  }, []);

  const load = useCallback(async () => {
    try {
      apply(await getStudentPreferences());
    } catch (err) {
      setLoadError(err.message);
    }
  }, [apply]);

  useEffect(() => {
    let ignore = false;
    getStudentPreferences()
      .then((data) => !ignore && apply(data))
      .catch((err) => !ignore && setLoadError(err.message));
    return () => {
      ignore = true;
    };
  }, [apply, refreshKey]);

  useEffect(() => {
    if (mode === "confirm-reset") resetHeadingRef.current?.focus();
    if (mode === "edit") editHeadingRef.current?.focus();
  }, [mode]);

  const startEdit = () => {
    setForm(toForm(prefs));
    setErrors({});
    setMessage(null);
    setMode("edit");
  };

  const set = (key, value) => setForm((f) => ({ ...f, [key]: value }));

  const save = async (e) => {
    e.preventDefault();
    const errs = validatePreferenceForm(form);
    setErrors(errs);
    if (Object.keys(errs).length) return;
    setBusy(true);
    setMessage(null);
    try {
      const res = await savePreferences(toUpdates(form));
      setPrefs(res.preferences);
      setStorage({ durable: res.durable, message: res.storage_message });
      setMode("view");
      setMessage({
        tone: "success",
        text: res.durable ? "Saved and verified." : "Saved and verified in temporary demo storage (cleared when the server restarts).",
      });
      onChanged?.();
    } catch (err) {
      setMessage({ tone: "danger", text: `${err.message} Your previous preferences are unchanged unless the page shows otherwise after reloading.` });
    } finally {
      setBusy(false);
    }
  };

  const doReset = async () => {
    setBusy(true);
    setMessage(null);
    try {
      const res = await resetPreferences();
      setPrefs(res.preferences);
      setMode("view");
      setMessage({ tone: "success", text: "Preferences reset to defaults and verified." });
      onChanged?.();
    } catch (err) {
      setMessage({ tone: "danger", text: err.message });
      setMode("view");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card className="p-4 sm:p-5" aria-labelledby={`${uid}-heading`}>
      <SectionTitle
        id={`${uid}-heading`}
        icon={Brain}
        title="Study preferences"
        subtitle="CampusPilot uses these when it plans your study time."
        action={
          mode === "view" && prefs ? (
            <Button variant="ghost" icon={Pencil} onClick={startEdit} className="px-3">
              Edit
            </Button>
          ) : null
        }
      />

      <div className="mt-4 space-y-3" aria-live="polite">
        {message && (
          <Notice tone={message.tone} role={message.tone === "danger" ? "alert" : "status"}>
            {message.text}
          </Notice>
        )}
        {loadError && (
          <Notice tone="danger" title="Preferences could not be loaded" action={<Button onClick={load}>Try again</Button>}>
            {loadError}
          </Notice>
        )}
        {!prefs && !loadError && <p className="text-sm text-ink-muted">Loading preferences…</p>}
      </div>

      {prefs && mode === "view" && (
        <div className="mt-1 space-y-4">
          <Summary prefs={prefs} />
          {!storage.durable && storage.message && <p className="text-xs text-amber-200/90">{storage.message}</p>}
          <div className="flex justify-end border-t border-line pt-3">
            <Button variant="ghost" icon={RotateCcw} onClick={() => {
                setMessage(null);
                setMode("confirm-reset");
              }} className="text-rose-300 hover:text-rose-200">
              Reset to defaults
            </Button>
          </div>
        </div>
      )}

      {prefs && mode === "confirm-reset" && (
        <div role="alertdialog" aria-labelledby={`${uid}-reset-title`} aria-describedby={`${uid}-reset-desc`} className="mt-1 rounded-xl border border-rose-500/40 bg-rose-500/5 p-4">
          <h3 id={`${uid}-reset-title`} ref={resetHeadingRef} tabIndex={-1} className="text-sm font-semibold text-ink">
            Reset all study preferences?
          </h3>
          <p id={`${uid}-reset-desc`} className="mt-1 text-sm text-ink-muted">
            This permanently clears your study window, session and break lengths, subjects, timing preferences and planning notes. Your tasks
            and schedule are not affected. This cannot be undone.
          </p>
          <div className="mt-3 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <Button onClick={() => setMode("view")} disabled={busy}>
              Keep my preferences
            </Button>
            <Button variant="danger" icon={Trash2} onClick={doReset} loading={busy}>
              Yes, reset preferences
            </Button>
          </div>
        </div>
      )}

      {form && mode === "edit" && (
        <form onSubmit={save} noValidate className="mt-1 space-y-4">
          <h3 ref={editHeadingRef} tabIndex={-1} className="sr-only">
            Edit study preferences
          </h3>
          <div className="grid grid-cols-2 gap-3">
            <Field id={`${uid}-start`} label="Earliest start" error={errors.preferred_study_start}>
              <input id={`${uid}-start`} type="time" step="900" className={inputClass} value={form.preferred_study_start} onChange={(e) => set("preferred_study_start", e.target.value)} aria-invalid={Boolean(errors.preferred_study_start) || undefined} aria-describedby={errors.preferred_study_start ? `${uid}-start-error` : undefined} />
            </Field>
            <Field id={`${uid}-end`} label="Latest end" error={errors.preferred_study_end}>
              <input id={`${uid}-end`} type="time" step="900" className={inputClass} value={form.preferred_study_end} onChange={(e) => set("preferred_study_end", e.target.value)} aria-invalid={Boolean(errors.preferred_study_end) || undefined} aria-describedby={errors.preferred_study_end ? `${uid}-end-error` : undefined} />
            </Field>
            <Field id={`${uid}-session`} label="Session (min)" error={errors.preferred_session_minutes}>
              <input id={`${uid}-session`} type="number" inputMode="numeric" min="15" max="360" step="5" className={inputClass} value={form.preferred_session_minutes} onChange={(e) => set("preferred_session_minutes", e.target.value)} aria-invalid={Boolean(errors.preferred_session_minutes) || undefined} aria-describedby={errors.preferred_session_minutes ? `${uid}-session-error` : undefined} />
            </Field>
            <Field id={`${uid}-break`} label="Break (min)" error={errors.preferred_break_minutes}>
              <input id={`${uid}-break`} type="number" inputMode="numeric" min="0" max="120" step="5" className={inputClass} value={form.preferred_break_minutes} onChange={(e) => set("preferred_break_minutes", e.target.value)} aria-invalid={Boolean(errors.preferred_break_minutes) || undefined} aria-describedby={errors.preferred_break_minutes ? `${uid}-break-error` : undefined} />
            </Field>
          </div>

          <fieldset aria-describedby={errors.preferred_study_days ? `${uid}-days-error` : undefined}>
            <legend className="mb-1.5 text-sm font-medium text-ink">Study days</legend>
            <div className="grid grid-cols-4 gap-1.5 sm:grid-cols-7">
              {DAYS.map((d) => {
                const on = form.preferred_study_days.includes(d);
                return (
                  <button
                    key={d}
                    type="button"
                    aria-pressed={on}
                    onClick={() => set("preferred_study_days", on ? form.preferred_study_days.filter((x) => x !== d) : DAYS.filter((x) => x === d || form.preferred_study_days.includes(x)))}
                    className={cx("min-h-11 rounded-xl border text-sm font-medium", on ? "border-accent/60 bg-accent/15 text-ink" : "border-line bg-canvas text-ink-faint")}
                  >
                    <span aria-hidden="true">{d.slice(0, 3)}</span>
                    <span className="sr-only">{d}</span>
                  </button>
                );
              })}
            </div>
            {errors.preferred_study_days && <p id={`${uid}-days-error`} className="mt-1 text-xs text-rose-300">{errors.preferred_study_days}</p>}
          </fieldset>

          <Field id={`${uid}-subjects`} label="Subjects" hint="Separate with commas, e.g. DBMS, DAA, OS">
            <input id={`${uid}-subjects`} className={inputClass} value={form.preferred_subjects} onChange={(e) => set("preferred_subjects", e.target.value)} maxLength={400} aria-describedby={`${uid}-subjects-hint`} />
          </Field>

          <fieldset aria-describedby={errors.timings ? `${uid}-timings-error` : undefined}>
            <legend className="mb-1.5 text-sm font-medium text-ink">Best time of day per subject</legend>
            <ul className="space-y-2">
              {form.timings.map((t, i) => (
                <li key={i} className="flex items-center gap-2">
                  <label className="sr-only" htmlFor={`${uid}-ts-${i}`}>Subject {i + 1}</label>
                  <input id={`${uid}-ts-${i}`} className={cx(inputClass, "min-w-0 flex-1")} placeholder="Subject" maxLength={40} value={t.subject} onChange={(e) => set("timings", form.timings.map((x, j) => (j === i ? { ...x, subject: e.target.value } : x)))} />
                  <label className="sr-only" htmlFor={`${uid}-tw-${i}`}>Time of day for subject {i + 1}</label>
                  <select id={`${uid}-tw-${i}`} className={cx(inputClass, "w-32 shrink-0")} value={t.when} onChange={(e) => set("timings", form.timings.map((x, j) => (j === i ? { ...x, when: e.target.value } : x)))}>
                    {TIMINGS.map((w) => (
                      <option key={w} value={w}>
                        {w[0].toUpperCase() + w.slice(1)}
                      </option>
                    ))}
                  </select>
                  <button type="button" onClick={() => set("timings", form.timings.filter((_, j) => j !== i))} aria-label={`Remove timing for ${t.subject || `row ${i + 1}`}`} className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl text-ink-faint hover:bg-raised hover:text-rose-300">
                    <X className="h-4 w-4" aria-hidden="true" />
                  </button>
                </li>
              ))}
            </ul>
            {errors.timings && <p id={`${uid}-timings-error`} className="mt-1 text-xs text-rose-300">{errors.timings}</p>}
            {form.timings.length < 20 && (
              <Button variant="ghost" icon={Plus} className="mt-1 px-2" onClick={() => set("timings", [...form.timings, { subject: "", when: "evening" }])}>
                Add subject timing
              </Button>
            )}
          </fieldset>

          <Field id={`${uid}-notes`} label="Planning notes" hint="One per line. Don't include passwords or personal details.">
            <textarea id={`${uid}-notes`} rows={3} className={cx(inputClass, "py-2.5")} value={form.planning_notes} onChange={(e) => set("planning_notes", e.target.value)} maxLength={2000} aria-describedby={`${uid}-notes-hint`} />
          </Field>

          <div className="flex flex-col-reverse gap-2 border-t border-line pt-3 sm:flex-row sm:justify-end">
            <Button onClick={() => setMode("view")} disabled={busy}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" icon={Check} loading={busy}>
              Save preferences
            </Button>
          </div>
        </form>
      )}
    </Card>
  );
}

export default StudentPreferencesCard;
