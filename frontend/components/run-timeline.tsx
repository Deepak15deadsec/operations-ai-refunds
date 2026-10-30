"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { label, time } from "@/lib/format";
import type { RunEvent } from "@/lib/types";
import { Icon, type IconName } from "./icons";

type D = RunEvent["data"];
type Tone = "good" | "warn" | "bad" | "info" | "neutral";

const EVENTS: Record<string, { icon: IconName; tone: Tone; text: (d: D) => string }> = {
  run_created: { icon: "play", tone: "neutral", text: (d) => (d.mode === "batch" ? "Batch run created" : `Run created for ${d.ticket_number}`) },
  structured_output_retry: { icon: "alert", tone: "warn", text: () => "Structured output invalid; retrying once with feedback" },
  investigation_completed: { icon: "sparkle", tone: "info", text: (d) => `Investigation complete: ${d.summary}` },
  action_proposed: { icon: "shield", tone: "neutral", text: (d) => `Proposed ${label(String(d.action_type))}; passed backend validation` },
  action_invalid: { icon: "x", tone: "bad", text: (d) => `Proposed ${label(String(d.action_type))}; rejected by backend (${label(String(d.status_reason))})` },
  approval_requested: { icon: "clock", tone: "warn", text: (d) => `Waiting for approval: ${label(String(d.action_type))}` },
  approval_approved: { icon: "check", tone: "good", text: (d) => `${d.decided_by} approved ${label(String(d.action_type))}` },
  approval_rejected: { icon: "x", tone: "bad", text: (d) => `${d.decided_by} rejected ${label(String(d.action_type))}` },
  approval_expired: { icon: "clock", tone: "bad", text: () => "Approval expired" },
  action_executed: { icon: "check", tone: "good", text: (d) => `Executed ${label(String(d.action_type))} (simulated)` },
  action_failed: { icon: "alert", tone: "bad", text: (d) => `Blocked ${label(String(d.action_type))}: ${label(String(d.reason))}` },
  batch_fanned_out: { icon: "layers", tone: "neutral", text: (d) => `Batch selected ${(d.ticket_numbers as string[]).join(", ") || "no tickets"}` },
  run_completed: { icon: "flag", tone: "good", text: (d) => `Run finished: ${label(String(d.status))}` },
};
const STREAMED = [...Object.keys(EVENTS), "status_changed", "tool_started", "tool_completed", "tool_failed"];

const toneText: Record<Tone, string> = { good: "text-good", warn: "text-warn", bad: "text-bad", info: "text-info", neutral: "text-ink" };
const toneBubble: Record<Tone, string> = {
  good: "bg-good-soft text-good", warn: "bg-warn-soft text-warn", bad: "bg-bad-soft text-bad", info: "bg-info-soft text-info", neutral: "bg-subtle text-muted",
};

type Item =
  | { kind: "phase"; key: number; status: string; at: string; run: string }
  | { kind: "tool"; key: number; tool: string; at: string; run: string; ms?: number; ok?: boolean; error?: string; preview?: string; domainError?: boolean }
  | { kind: "event"; key: number; event: string; data: D; at: string; run: string };

function buildItems(events: RunEvent[]): Item[] {
  const items: Item[] = [];
  const open = new Map<string, Extract<Item, { kind: "tool" }>[]>();
  const lastPhase = new Map<string, string>();
  for (const e of events) {
    const run = String(e.data.run_id);
    const at = String(e.data.created_at);
    if (e.event === "status_changed") {
      const status = String(e.data.status);
      if (lastPhase.get(run) !== status) items.push({ kind: "phase", key: e.id, status, at, run });
      lastPhase.set(run, status);
    } else if (e.event === "tool_started") {
      const item = { kind: "tool" as const, key: e.id, tool: String(e.data.tool), at, run };
      items.push(item);
      const k = `${run}:${item.tool}`;
      open.set(k, [...(open.get(k) ?? []), item]);
    } else if (e.event === "tool_completed" || e.event === "tool_failed") {
      const k = `${run}:${e.data.tool}`;
      const queue = open.get(k) ?? [];
      const item = queue.shift() ?? (items.push({ kind: "tool", key: e.id, tool: String(e.data.tool), at, run }), items.at(-1) as Extract<Item, { kind: "tool" }>);
      item.ms = Number(e.data.duration_ms);
      item.ok = e.event === "tool_completed";
      item.domainError = Boolean(e.data.domain_error);
      item.error = e.event === "tool_failed" ? `${e.data.error}: ${e.data.message}` : undefined;
      item.preview = e.data.result_preview ? String(e.data.result_preview) : undefined;
    } else {
      items.push({ kind: "event", key: e.id, event: e.event, data: e.data, at, run });
    }
  }
  return items;
}

/** Live run timeline over SSE (native EventSource via the cookie-authenticated proxy; reconnects
 * resume with Last-Event-ID, and ids are de-duplicated). */
export function RunTimeline({ runId, onEvent, runLabels }: { runId: string; onEvent?: (e: RunEvent) => void; runLabels?: Record<string, string> }) {
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [state, setState] = useState<"connecting" | "live" | "ended" | "reconnecting">("connecting");
  const seen = useRef(new Set<number>());
  const callback = useRef(onEvent);
  callback.current = onEvent;

  useEffect(() => {
    seen.current = new Set();
    setEvents([]);
    const source = new EventSource(`/api/proxy/api/v1/runs/${runId}/events`);
    const handle = (e: MessageEvent) => {
      const id = Number(e.lastEventId);
      if (!id || seen.current.has(id)) return;
      seen.current.add(id);
      const event = { id, event: e.type, data: JSON.parse(e.data) } as RunEvent;
      setEvents((prev) => [...prev, event]);
      callback.current?.(event);
    };
    for (const name of STREAMED) source.addEventListener(name, handle);
    source.addEventListener("stream_end", () => { setState("ended"); source.close(); });
    source.onopen = () => setState("live");
    source.onerror = () => setState((s) => (s === "ended" ? s : "reconnecting"));
    return () => source.close();
  }, [runId]);

  const items = useMemo(() => buildItems(events), [events]);
  const tag = (run: string) => (runLabels?.[run] ? <span className="mr-1.5 rounded bg-subtle px-1.5 py-px font-mono text-[10px] text-muted">{runLabels[run]}</span> : null);

  return (
    <div>
      <p className="mb-4 flex items-center gap-2 text-xs text-muted" aria-live="polite">
        {state === "live" ? (
          <><span className="relative flex size-2"><span className="absolute inline-flex size-full animate-ping rounded-full bg-good opacity-60" /><span className="relative size-2 rounded-full bg-good" /></span>Live</>
        ) : state === "ended" ? "Run finished. Showing the full durable history." : state === "reconnecting" ? "Reconnecting…" : "Connecting…"}
      </p>
      {items.length === 0 ? (
        <p className="text-sm text-muted">No events yet.</p>
      ) : (
        <ol className="relative space-y-3 before:absolute before:top-2 before:bottom-2 before:left-[11px] before:w-px before:bg-line" data-testid="timeline">
          {items.map((item) => {
            if (item.kind === "phase") {
              return (
                <li key={item.key} className="relative flex items-center gap-3 pl-0" data-event="status_changed">
                  <span className="relative z-10 ml-[7px] size-2.5 rounded-full border-2 border-surface bg-muted" />
                  <span className="text-[11px] font-semibold tracking-wide text-muted uppercase">{tag(item.run)}{label(item.status)}</span>
                  <span className="ml-auto font-mono text-[11px] text-muted">{time(item.at)}</span>
                </li>
              );
            }
            if (item.kind === "tool") {
              const pending = item.ok === undefined;
              const bad = item.ok === false || item.domainError;
              return (
                <li key={item.key} className="relative flex gap-3" data-event="tool">
                  <span className={`relative z-10 flex size-6 shrink-0 items-center justify-center rounded-full ${bad ? toneBubble.bad : pending ? toneBubble.info : toneBubble.neutral}`}>
                    <Icon name="wrench" size={12} />
                  </span>
                  <details className="group min-w-0 flex-1">
                    <summary className="flex cursor-pointer list-none items-center gap-2 text-sm">
                      {tag(item.run)}
                      <span className="font-mono text-ink">{item.tool}</span>
                      <span className={`text-xs ${bad ? "text-bad" : "text-muted"}`}>
                        {pending ? "running…" : item.ok ? `${item.ms} ms${item.domainError ? " · returned an error" : ""}` : `failed after ${item.ms} ms`}
                      </span>
                      <span className="ml-auto font-mono text-[11px] text-muted">{time(item.at)}</span>
                    </summary>
                    {(item.preview || item.error) && (
                      <pre className="mt-1.5 max-h-40 overflow-auto rounded-md bg-subtle p-2 text-[11px] whitespace-pre-wrap text-muted">{item.error ?? item.preview}</pre>
                    )}
                  </details>
                </li>
              );
            }
            const meta = EVENTS[item.event] ?? { icon: "clock" as IconName, tone: "neutral" as Tone, text: () => label(item.event) };
            return (
              <li key={item.key} className="relative flex gap-3" data-event={item.event}>
                <span className={`relative z-10 flex size-6 shrink-0 items-center justify-center rounded-full ${toneBubble[meta.tone]}`}>
                  <Icon name={meta.icon} size={12} />
                </span>
                <span className={`min-w-0 flex-1 text-sm ${toneText[meta.tone]}`}>{tag(item.run)}{meta.text(item.data)}</span>
                <span className="shrink-0 font-mono text-[11px] text-muted">{time(item.at)}</span>
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}
