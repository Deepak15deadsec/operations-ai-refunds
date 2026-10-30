"use client";
import Link from "next/link";
import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { ACTION_TITLE, hoursUntil, label, money, relative, when } from "@/lib/format";
import type { Approval, Evidence } from "@/lib/types";
import { Icon, type IconName } from "./icons";
import { notifyApprovalsChanged, useToast } from "./toast";
import { Avatar, Badge, Button, ErrorBox, inputClass, SimulatedTag } from "./ui";

const ACTION_META: Record<Approval["action_type"], { icon: IconName; title: string }> = {
  refund: { icon: "money", title: ACTION_TITLE.refund! },
  send_reply: { icon: "mail", title: ACTION_TITLE.send_reply! },
  escalate_ticket: { icon: "flag", title: ACTION_TITLE.escalate_ticket! },
};

function ActionBody({ approval }: { approval: Approval }) {
  const p = approval.payload as Record<string, string | number>;
  const check = approval.evidence.find((e) => e.source_type === "policy_evaluation");
  if (approval.action_type === "refund") {
    return (
      <div>
        <p className="text-2xl font-semibold tabular-nums tracking-tight text-ink" data-testid="refund-amount">
          {money(Number(p.amount_minor), String(p.currency))}
        </p>
        <p className="text-sm text-muted">Order {p.order_number} · policy {approval.policy_version}</p>
        {check && (
          <p className={`mt-2 inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs ${check.eligible ? "bg-good-soft text-good" : "bg-bad-soft text-bad"}`}>
            <Icon name={check.eligible ? "check" : "x"} size={14} />
            Backend policy check: {check.eligible ? `eligible up to ${money(check.max_amount_minor)}` : "not eligible"}
          </p>
        )}
      </div>
    );
  }
  if (approval.action_type === "send_reply") {
    return (
      <div>
        <p className="mb-1.5 text-xs text-muted">To {String(p.destination)}</p>
        <blockquote className="whitespace-pre-wrap rounded-lg border-l-2 border-accent/60 bg-subtle px-3 py-2 text-sm text-ink">
          {String(p.message_body)}
        </blockquote>
      </div>
    );
  }
  return (
    <p className="text-sm text-ink">
      Move ticket from <Badge value={String(p.from_status)} /> to <Badge value="escalated" />
    </p>
  );
}

export function ApprovalRow({ approval, onDecided }: { approval: Approval; onDecided?: () => void }) {
  const toast = useToast();
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<"approve" | "reject" | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const meta = ACTION_META[approval.action_type];
  const pending = approval.status === "pending";

  async function decide(decision: "approve" | "reject") {
    setBusy(decision);
    setError(null);
    try {
      await api<Approval>(`/api/v1/approvals/${approval.approval_id}/decision`, {
        method: "POST",
        body: JSON.stringify({ decision, note: note || null }),
      });
      toast(`${meta.title} for ${approval.ticket_number} ${decision === "approve" ? "approved and queued for execution" : "rejected"}`,
            decision === "approve" ? "good" : "info");
      notifyApprovalsChanged();
      onDecided?.();
    } catch (e) {
      setError(e as ApiError);
      toast((e as ApiError).message, "bad");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="grid gap-4 px-4 py-4 md:grid-cols-[1fr_auto]" data-testid={`approval-${approval.action_type}`}>
      <div className="flex min-w-0 gap-3">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-subtle text-muted"><Icon name={meta.icon} size={18} /></span>
        <div className="min-w-0 flex-1 space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-semibold text-ink">{meta.title}</h3>
            <SimulatedTag />
            {!pending && <Badge value={approval.status} />}
            {approval.action_status_reason && <Badge kind="bad">{label(approval.action_status_reason)}</Badge>}
          </div>
          <ActionBody approval={approval} />
          <p className="text-sm text-muted"><span className="font-medium text-ink">Agent&apos;s reason:</span> {approval.reason}</p>
          <details className="text-xs text-muted">
            <summary className="cursor-pointer select-none hover:text-ink">Approval details</summary>
            <dl className="mt-2 grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1">
              <dt>Fingerprint</dt><dd className="break-all font-mono">{approval.action_hash}</dd>
              <dt>Created</dt><dd>{when(approval.created_at)}</dd>
              <dt>Expires</dt><dd>{when(approval.expires_at)}</dd>
              <dt>Reviewers</dt><dd>{approval.permitted_reviewer_roles.join(", ")}</dd>
              {approval.decided_at && (<><dt>Decided</dt><dd>{approval.decided_by_name ?? approval.decided_by} · {when(approval.decided_at)}</dd></>)}
              {approval.decision_note && (<><dt>Note</dt><dd>{approval.decision_note}</dd></>)}
            </dl>
          </details>
        </div>
      </div>

      {pending && (
        <div className="flex w-full flex-col gap-2 md:w-64">
          <input className={inputClass} placeholder="Decision note (optional)" aria-label={`Decision note for ${meta.title}`}
                 value={note} onChange={(e) => setNote(e.target.value)} maxLength={1000} />
          <div className="grid grid-cols-2 gap-2">
            <Button variant="danger" icon="x" onClick={() => decide("reject")} disabled={!!busy}>{busy === "reject" ? "Rejecting…" : "Reject"}</Button>
            <Button icon="check" onClick={() => decide("approve")} disabled={!!busy}>{busy === "approve" ? "Approving…" : "Approve"}</Button>
          </div>
          <ErrorBox error={error} />
        </div>
      )}
    </div>
  );
}

function EvidenceList({ evidence }: { evidence: Evidence[] }) {
  const items = evidence.filter((e) => e.claim);
  if (!items.length) return null;
  return (
    <ul className="space-y-1.5">
      {items.map((e, i) => (
        <li key={i} className="flex gap-2 text-sm">
          <Icon name="check" size={14} className="mt-1 shrink-0 text-muted" />
          <span className="text-ink">
            {e.claim} <span className="rounded bg-subtle px-1.5 py-px font-mono text-[11px] text-muted">{e.source_type} {e.source_id}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}

/** All approvals of one run (= one ticket): shared context once, then one row per action. */
export function ApprovalGroup({ approvals, onDecided }: { approvals: Approval[]; onDecided?: () => void }) {
  const first = approvals[0]!;
  const evidence = approvals.reduce<Evidence[]>((best, a) => (a.evidence.length > best.length ? a.evidence : best), []);
  const soonest = approvals.filter((a) => a.status === "pending").map((a) => a.expires_at).sort()[0];
  const urgent = soonest ? hoursUntil(soonest) < 2 : false;
  return (
    <article className="overflow-hidden rounded-xl border border-line bg-surface shadow-[0_1px_2px_rgba(0,0,0,0.04)]"
             data-testid={`approval-group-${first.ticket_number}`}>
      <header className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line bg-subtle/50 px-4 py-3">
        <div className="min-w-0">
          <Link href={`/tickets/${first.ticket_number}`} className="font-mono text-sm font-semibold text-accent hover:underline">{first.ticket_number}</Link>
          <span className="ml-2 text-sm text-ink">{first.ticket_subject}</span>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-3 text-xs text-muted">
          <span className="flex items-center gap-1.5"><Avatar name={first.requested_by_name} size={20} /> Requested by {first.requested_by_name ?? "unknown"} · {relative(first.created_at)}</span>
          {soonest && (
            <span className={`flex items-center gap-1 ${urgent ? "font-medium text-bad" : ""}`}><Icon name="clock" size={14} /> Expires {relative(soonest)}</span>
          )}
          <Link href={`/runs/${first.run_id}`} className="flex items-center gap-1 text-accent hover:underline">View run <Icon name="arrow" size={14} /></Link>
        </div>
      </header>
      {evidence.length > 0 && (
        <div className="border-b border-line px-4 py-3">
          <p className="mb-2 text-xs font-semibold tracking-wide text-muted uppercase">Evidence gathered by the agent</p>
          <EvidenceList evidence={evidence} />
        </div>
      )}
      <div className="divide-y divide-line">
        {approvals.map((a) => <ApprovalRow key={a.approval_id} approval={a} onDecided={onDecided} />)}
      </div>
    </article>
  );
}
