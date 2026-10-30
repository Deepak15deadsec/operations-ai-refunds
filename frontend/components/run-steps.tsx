import type { Action } from "@/lib/types";
import { Icon } from "./icons";

const STEPS = ["Investigate", "Validate", "Approve", "Execute", "Done"] as const;

const ORDER: Record<string, number> = {
  queued: 0, running: 0, investigating: 0, validating: 1, awaiting_approval: 2, resuming: 3, executing: 3,
  completed: 4, completed_no_action: 4, rejected: 4, failed: 4, cancelled: 4, needs_human_review: 4,
};
const BAD_END = ["failed", "cancelled", "needs_human_review", "rejected"];

/** Progress across the run's phases, with per-action context on the approval step. */
export function RunSteps({ status, actions = [] }: { status: string; actions?: Action[] }) {
  const current = ORDER[status] ?? 0;
  const finished = current === 4;
  const approvable = actions.filter((a) => a.approval);
  const decided = approvable.filter((a) => a.approval!.status !== "pending").length;

  const detail = (i: number): string | null => {
    if (i === 2 && approvable.length) return `${decided} of ${approvable.length} decided`;
    if (i === 3 && approvable.length) {
      const done = actions.filter((a) => a.status === "completed").length;
      return done ? `${done} executed` : null;
    }
    if (i === 4 && finished) return status.replaceAll("_", " ");
    return null;
  };

  return (
    <ol className="grid grid-cols-5 gap-2" aria-label="Run progress">
      {STEPS.map((text, i) => {
        const done = i < current || (finished && i === 4);
        const active = i === current && !finished;
        const bad = finished && i === 4 && BAD_END.includes(status);
        const bar = bad ? "bg-bad" : done ? "bg-good" : active ? "bg-info" : "bg-line";
        return (
          <li key={text} aria-current={active ? "step" : undefined} className="min-w-0">
            <div className={`h-1.5 rounded-full ${bar} ${active ? "animate-pulse" : ""}`} />
            <p className={`mt-2 flex items-center gap-1 text-xs font-medium ${bad ? "text-bad" : done ? "text-good" : active ? "text-info" : "text-muted"}`}>
              {done && !bad && <Icon name="check" size={12} />}
              {bad && <Icon name="x" size={12} />}
              {text}
            </p>
            {detail(i) && <p className={`truncate text-[11px] text-muted ${i === 4 ? "capitalize" : ""}`}>{detail(i)}</p>}
          </li>
        );
      })}
    </ol>
  );
}
