import { useCallback, useEffect, useRef, useState } from "react";
import { CalendarCheck, ClipboardList, LoaderCircle, RefreshCw, ShieldCheck, Sparkles } from "lucide-react";
import { approveAgent, getAgentStatus, rejectAgent, runAgent } from "./api/agent";
import AgentActivity from "./components/AgentActivity";
import AgentPlan from "./components/AgentPlan";
import AgentResult from "./components/AgentResult";
import AppHeader from "./components/AppHeader";
import ApprovalCard from "./components/ApprovalCard";
import BottomNav from "./components/BottomNav";
import GoalInput from "./components/GoalInput";
import StudentPreferencesCard from "./components/StudentPreferencesCard";
import { Button, Card, Notice } from "./components/ui";
import { cx } from "./lib/classes";

const HOW_IT_WORKS = [
  { icon: Sparkles, title: "Describe your goal", text: "Subjects, hours, and anything already booked." },
  { icon: ClipboardList, title: "Get a step-by-step plan", text: "It reads your schedule first and avoids conflicts." },
  { icon: ShieldCheck, title: "Approve every change", text: "Nothing is saved until you say yes." },
  { icon: CalendarCheck, title: "Verified results", text: "Each saved item is read back to confirm it." },
];

function Intro() {
  return (
    <Card className="p-4 sm:p-5" aria-labelledby="intro-heading">
      <h2 id="intro-heading" className="text-base font-semibold tracking-tight text-ink">
        How CampusPilot works
      </h2>
      <ol className="mt-3 grid gap-2 sm:grid-cols-2">
        {HOW_IT_WORKS.map(({ icon: Icon, title, text }, i) => (
          <li key={title} className="flex items-start gap-3 rounded-xl border border-line bg-canvas p-3">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-raised text-accent" aria-hidden="true">
              <Icon className="h-4 w-4" />
            </span>
            <div className="min-w-0 text-sm">
              <p className="font-medium text-ink">
                <span className="sr-only">Step {i + 1}: </span>
                {title}
              </p>
              <p className="text-ink-muted">{text}</p>
            </div>
          </li>
        ))}
      </ol>
      <p className="mt-3 text-xs text-ink-faint">
        CampusPilot works with its own task list, schedule and notes. It does not connect to Google Calendar or other apps.
      </p>
    </Card>
  );
}

function Planning() {
  return (
    <Card className="p-5" aria-live="polite" aria-busy="true">
      <div className="flex items-center gap-3">
        <LoaderCircle className="h-5 w-5 shrink-0 text-accent motion-safe:animate-spin" aria-hidden="true" />
        <div>
          <p className="text-sm font-medium text-ink">Planning…</p>
          <p className="text-sm text-ink-muted">Reading your schedule and preferences, then building a step-by-step plan.</p>
        </div>
      </div>
    </Card>
  );
}

export function App() {
  const [goal, setGoal] = useState("");
  const [loading, setLoading] = useState(false);
  const [runError, setRunError] = useState(null);
  const [agentStatus, setAgentStatus] = useState(null);
  const [executionResult, setExecutionResult] = useState(null);
  const [decision, setDecision] = useState(null); // "approve" | "reject" | null
  const [decisionError, setDecisionError] = useState("");
  const [approvalClosed, setApprovalClosed] = useState(false);
  const [view, setView] = useState("plan");
  const [refreshKey, setRefreshKey] = useState(0);
  const [announcement, setAnnouncement] = useState("");
  const inFlight = useRef(false);
  const goalRef = useRef(null);
  const resultsRef = useRef(null);

  const fetchStatus = useCallback(async () => {
    try {
      setAgentStatus(await getAgentStatus());
    } catch {
      setAgentStatus({ status: "offline" });
    }
  }, []);

  useEffect(() => {
    let ignore = false;
    getAgentStatus()
      .then((data) => !ignore && setAgentStatus(data))
      .catch(() => !ignore && setAgentStatus({ status: "offline" }));
    return () => {
      ignore = true;
    };
  }, []);

  const focusResults = () =>
    requestAnimationFrame(() => {
      resultsRef.current?.focus({ preventScroll: true });
      resultsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    });

  const handleRun = async (cleanGoal) => {
    if (inFlight.current) return;
    inFlight.current = true;
    setLoading(true);
    setRunError(null);
    setDecisionError("");
    setApprovalClosed(false);
    setExecutionResult(null);
    setAnnouncement("Planning your goal.");
    try {
      const result = await runAgent(cleanGoal);
      setExecutionResult(result);
      setRefreshKey((k) => k + 1);
      setAnnouncement(
        result.status === "waiting_approval"
          ? `Plan ready. ${result.approval_requests?.length || 0} change(s) need your approval.`
          : result.status === "needs_clarification"
            ? "CampusPilot needs one more detail."
            : `Finished: ${result.workflow?.status || result.status}.`,
      );
      focusResults();
    } catch (err) {
      setRunError(err);
      setAnnouncement(`Planning failed. ${err.message}`);
    } finally {
      setLoading(false);
      inFlight.current = false;
    }
  };

  const decide = async (kind) => {
    const approvalId = executionResult?.approval_id;
    if (!approvalId || inFlight.current) return;
    inFlight.current = true;
    setDecision(kind);
    setDecisionError("");
    try {
      const resp =
        kind === "approve"
          ? await approveAgent(approvalId, executionResult.approval_requests?.[0]?.payload_hash)
          : await rejectAgent(approvalId);
      if (resp.execution_result) setExecutionResult(resp.execution_result);
      setRefreshKey((k) => k + 1);
      setAnnouncement(
        kind === "approve"
          ? resp.success
            ? "Changes saved and verified."
            : "Some changes could not be completed. Review the steps."
          : "Changes rejected. Nothing was saved.",
      );
      fetchStatus();
    } catch (err) {
      if (err.kind === "expired" || err.kind === "conflict" || err.kind === "not_found") {
        setApprovalClosed(true);
        setDecisionError(
          err.kind === "expired"
            ? "This approval expired, so nothing was saved. Run your goal again to get a fresh plan."
            : err.kind === "conflict"
              ? `${err.message} Check Activity for the outcome.`
              : "This approval is no longer available (for example after a server restart). Nothing was saved. Run your goal again.",
        );
      } else {
        setDecisionError(err.message);
      }
      setAnnouncement(`Your decision was not applied. ${err.message}`);
    } finally {
      setDecision(null);
      inFlight.current = false;
    }
  };

  const waiting = executionResult?.status === "waiting_approval" && executionResult?.approval_requests?.length > 0;
  const showApproval = waiting && !approvalClosed;
  const editGoal = () => {
    setView("plan");
    requestAnimationFrame(() => goalRef.current?.focus());
  };

  const region = (id) => cx(view !== id && "hidden", "lg:block");

  return (
    <div className="min-h-dvh bg-canvas text-ink">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50 focus:rounded-lg focus:bg-surface focus:px-3 focus:py-2">
        Skip to content
      </a>
      <AppHeader agentStatus={agentStatus} onRefreshStatus={fetchStatus} />
      <p className="sr-only" aria-live="polite" role="status">
        {announcement}
      </p>

      <main id="main" className="pb-safe-nav mx-auto w-full max-w-6xl px-4 pt-4 sm:px-6 sm:pt-6">
        {agentStatus?.status === "offline" && (
          <Notice tone="danger" className="mb-4" title="Can't reach the CampusPilot server" action={<Button icon={RefreshCw} onClick={fetchStatus}>Retry</Button>}>
            Start the backend (see README) or check your connection. Your goal text is kept here.
          </Notice>
        )}

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] lg:gap-6">
          <div className="min-w-0 space-y-4 lg:space-y-6">
            <div className={region("plan")}>
              <GoalInput ref={goalRef} goal={goal} onChange={setGoal} onSubmit={handleRun} loading={loading} disabled={Boolean(decision)} />
            </div>
            <div className={region("memory")}>
              <StudentPreferencesCard refreshKey={refreshKey} onChanged={() => setRefreshKey((k) => k + 1)} />
            </div>
          </div>

          <div className="min-w-0 space-y-4 lg:space-y-6">
            <div className={cx(region("plan"), "space-y-4 lg:space-y-6")}>
              <div ref={resultsRef} tabIndex={-1} className="scroll-mt-20 space-y-4 focus:outline-none lg:space-y-6" aria-label="Results">
                {loading && <Planning />}
                {runError && (
                  <Notice
                    tone="danger"
                    role="alert"
                    title="CampusPilot couldn't plan that"
                    action={<Button icon={RefreshCw} onClick={() => handleRun(goal.trim())} disabled={!goal.trim()}>Try again</Button>}
                  >
                    {runError.message}
                  </Notice>
                )}
                {executionResult && <AgentResult executionResult={executionResult} onEditGoal={editGoal} />}
                {showApproval && (
                  <ApprovalCard
                    requests={executionResult.approval_requests}
                    expiresAt={executionResult.approval_requests?.[0]?.expires_at}
                    onApprove={() => decide("approve")}
                    onReject={() => decide("reject")}
                    busy={decision}
                    error={decisionError}
                  />
                )}
                {waiting && approvalClosed && decisionError && (
                  <Notice tone="warning" role="alert" title="Approval no longer available" action={<Button icon={RefreshCw} onClick={() => handleRun(executionResult.goal)}>Plan again</Button>}>
                    {decisionError}
                  </Notice>
                )}
                {executionResult && executionResult.status !== "needs_clarification" && <AgentPlan executionResult={executionResult} />}
                {!executionResult && !loading && !runError && <Intro />}
              </div>
            </div>
            <div className={region("activity")}>
              <AgentActivity refreshKey={refreshKey} />
            </div>
          </div>
        </div>
      </main>

      <BottomNav view={view} onChange={setView} attention={showApproval ? "plan" : null} />
    </div>
  );
}

export default App;
