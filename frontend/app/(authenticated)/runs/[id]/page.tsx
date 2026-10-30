"use client";
import Link from "next/link";
import { use, useCallback, useMemo, useRef, useState } from "react";
import { api, ApiError, useApi } from "@/lib/api";
import { actionTitle, duration, label, money, relative } from "@/lib/format";
import type { Action, RunDetail, RunEvent } from "@/lib/types";
import { Icon, type IconName } from "@/components/icons";
import { RunSteps } from "@/components/run-steps";
import { RunTimeline } from "@/components/run-timeline";
import { useToast } from "@/components/toast";
import { Avatar, Badge, Button, ButtonLink, Card, ErrorBox, KeyValue, Loading, PageTitle, SimulatedTag, StatusDot } from "@/components/ui";

const TERMINAL = ["completed", "completed_no_action", "rejected", "failed", "cancelled", "needs_human_review"];
const REFRESH_ON = new Set(["status_changed", "action_proposed", "action_invalid", "action_executed", "action_failed",
  "approval_approved", "approval_rejected", "approval_expired", "run_completed", "batch_fanned_out", "investigation_completed"]);
const ACTION_ORDER = ["refund", "send_reply", "escalate_ticket"];
const ACTION_ICON: Record<Action["action_type"], IconName> = { refund: "money", send_reply: "mail", escalate_ticket: "flag" };
const SOURCE_HREF = (type: string, id: string, ticket: string | null) =>
  type === "ticket" ? `/tickets/${id}` : type === "order" || type === "delivery_event" || type === "customer" ? `/tickets/${ticket}` : null;

function ActionRow({ action }: { action: Action }) {
  const p = action.payload as Record<string, string | number>;
  const pending = action.approval?.status === "pending";
  return (
    <li className="flex gap-3 py-4 first:pt-0 last:pb-0" data-testid={`action-${action.action_type}`}>
      <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-subtle text-muted"><Icon name={ACTION_ICON[action.action_type]} size={18} /></span>
      <div className="min-w-0 flex-1 space-y-1.5 text-sm">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-semibold text-ink">{actionTitle(action.action_type)}</span>
          <SimulatedTag />
          <Badge value={action.status} />
          {action.status_reason && <span className="text-xs text-bad">{label(action.status_reason)}</span>}
          {pending && <span className="ml-auto"><ButtonLink href="/approvals" variant="secondary" icon="shield">Review</ButtonLink></span>}
        </div>
        {action.action_type === "refund" && (
          <p className="text-ink"><span className="text-lg font-semibold tabular-nums">{money(Number(p.amount_minor), String(p.currency))}</span> for order {p.order_number}</p>
        )}
        {action.action_type === "send_reply" && (
          <blockquote className="whitespace-pre-wrap rounded-lg border-l-2 border-accent/60 bg-subtle px-3 py-2 text-ink">{p.message_body}</blockquote>
        )}
        <p className="text-muted">{action.reason}</p>
        {!action.approval && action.status === "failed" && (
          <p className="text-xs text-muted">Not sent for approval: the backend refused this proposal.</p>
        )}
      </div>
    </li>
  );
}

export default function RunPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const toast = useToast();
  const { data, error, loading, reload } = useApi<RunDetail>(`/api/v1/runs/${id}`);
  const [cancelError, setCancelError] = useState<ApiError | null>(null);
  const pending = useRef<ReturnType<typeof setTimeout> | null>(null);

  const onEvent = useCallback((e: RunEvent) => {
    if (!REFRESH_ON.has(e.event)) return;
    if (pending.current) clearTimeout(pending.current);
    pending.current = setTimeout(() => void reload(), 250);
  }, [reload]);

  const runLabels = useMemo(
    () => Object.fromEntries((data?.children ?? []).map((c) => [c.run_id, c.ticket_number ?? "?"])),
    [data?.children],
  );

  async function cancel() {
    try {
      await api(`/api/v1/runs/${id}/cancel`, { method: "POST" });
      toast("Run cancelled. Pending approvals were withdrawn.", "info");
      await reload();
    } catch (e) {
      setCancelError(e as ApiError);
    }
  }

  if (loading && !data) return <Card><Loading rows={8} /></Card>;
  if (error && !data) return <ErrorBox error={error} />;
  const run = data!;
  const finished = TERMINAL.includes(run.status);

  return (
    <>
      <PageTitle
        eyebrow={<Link href="/runs" className="hover:text-ink">← Runs</Link>}
        title={
          <span className="flex flex-wrap items-center gap-3">
            {run.mode === "batch" ? "Batch run" : <>Investigation of <Link href={`/tickets/${run.ticket_number}`} className="font-mono text-accent hover:underline">{run.ticket_number}</Link></>}
            <Badge value={run.status} />
          </span>
        }
        subtitle={
          <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <span className="flex items-center gap-1.5"><Avatar name={run.requested_by_name} size={18} /> {run.requested_by_name ?? "unknown"}</span>
            <span>started {relative(run.created_at)}</span>
            {run.finished_at && <span>took {duration(run.started_at, run.finished_at)}</span>}
            <span className="font-mono text-xs">{run.run_id.slice(0, 8)}</span>
          </span>
        }
        actions={!finished && <Button variant="secondary" icon="x" onClick={cancel}>Cancel run</Button>}
      />

      <Card className="mb-5"><RunSteps status={run.status} actions={run.actions} /></Card>
      <div className="mb-4 space-y-3">
        <ErrorBox error={cancelError} />
        {run.error_code && <ErrorBox error={{ message: `${label(run.error_code)}: ${run.error_message ?? ""}` }} />}
      </div>

      <div className="grid gap-5 lg:grid-cols-[3fr_2fr]">
        <div className="space-y-5">
          {run.mode === "batch" && (
            <Card title={`Child runs (${run.children.length})`} icon="layers" padded={false}>
              <ul className="divide-y divide-line">
                {run.children.map((c) => (
                  <li key={c.run_id}>
                    <Link href={`/runs/${c.run_id}`} className="flex items-center gap-3 px-4 py-2.5 text-sm hover:bg-subtle">
                      <StatusDot value={c.status} pulse={!TERMINAL.includes(c.status)} />
                      <span className="font-mono text-accent">{c.ticket_number}</span>
                      <Badge value={c.status} />
                      {c.error_code && <span className="text-xs text-bad">{label(c.error_code)}</span>}
                      <Icon name="chevron" className="ml-auto text-muted" />
                    </Link>
                  </li>
                ))}
              </ul>
            </Card>
          )}

          {run.findings ? (
            <Card title="Findings" icon="sparkle">
              <p className="text-sm leading-relaxed text-ink" data-testid="summary">{run.findings.summary}</p>
              <ul className="mt-4 space-y-2">
                {run.findings.findings.map((f, i) => {
                  const href = SOURCE_HREF(f.source_type, f.source_id, run.ticket_number);
                  const chip = <span className="rounded bg-subtle px-1.5 py-px font-mono text-[11px] text-muted">{f.source_type} {f.source_id}</span>;
                  return (
                    <li key={i} className="flex gap-2 text-sm">
                      <Icon name="check" size={14} className="mt-1 shrink-0 text-good" />
                      <span className="text-ink">{f.claim} {href ? <Link href={href} className="hover:opacity-80">{chip}</Link> : chip}</span>
                    </li>
                  );
                })}
              </ul>
            </Card>
          ) : run.mode === "ticket" && !finished ? (
            <Card title="Findings" icon="sparkle"><Loading rows={3} /></Card>
          ) : null}

          {run.mode === "ticket" && (
            <Card title="Proposed actions" icon="shield">
              {run.actions.length === 0 ? (
                <p className="text-sm text-muted">
                  {finished ? run.summary?.no_action_reasons?.join("; ") || "No actions were proposed." : "Waiting for the investigation…"}
                </p>
              ) : (
                <ul className="divide-y divide-line">{[...run.actions].sort((x, y) => ACTION_ORDER.indexOf(x.action_type) - ACTION_ORDER.indexOf(y.action_type)).map((a) => <ActionRow key={a.action_id} action={a} />)}</ul>
              )}
            </Card>
          )}

          <Card title="Instruction" icon="user">
            <p className="text-sm text-ink">{run.original_instruction}</p>
          </Card>

          {run.usage && (
            <Card title="Agent telemetry" icon="wrench">
              <KeyValue items={[
                ["Model", <span key="m" className="font-mono text-xs">{run.usage.model}</span>],
                ["Tool calls", `${run.usage.tool_calls}${run.usage.tool_errors ? ` (${run.usage.tool_errors} errors)` : ""}`],
                ["Tokens in / out", `${run.usage.input_tokens} / ${run.usage.output_tokens}`],
                ["Investigation time", `${(run.usage.duration_ms / 1000).toFixed(1)} s`],
              ]} />
            </Card>
          )}
        </div>

        <div className="lg:sticky lg:top-6 lg:self-start">
          <Card title="Timeline" icon="clock">
            <RunTimeline runId={id} onEvent={onEvent} runLabels={run.mode === "batch" ? runLabels : undefined} />
          </Card>
        </div>
      </div>
    </>
  );
}
