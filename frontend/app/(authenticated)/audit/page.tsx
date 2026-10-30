"use client";
import Link from "next/link";
import { useState } from "react";
import { useApi } from "@/lib/api";
import { label, relative, when } from "@/lib/format";
import type { AuditEvent } from "@/lib/types";
import { Icon, type IconName } from "@/components/icons";
import { Card, Empty, ErrorBox, Field, inputClass, Loading, PageTitle } from "@/components/ui";

const TYPES = ["", "run_started", "action_proposed", "action_rejected_by_validation", "approval_requested",
  "approval_approved", "approval_rejected", "approval_expired", "refund_executed", "send_reply_executed",
  "escalate_ticket_executed", "action_execution_blocked", "run_finished", "run_cancelled"];
const ACTOR: Record<string, IconName> = { user: "user", agent: "sparkle", system: "wrench" };

export default function AuditPage() {
  const [type, setType] = useState("");
  const { data, error, loading } = useApi<AuditEvent[]>(`/api/v1/audit-events?limit=300${type ? `&event_type=${type}` : ""}`);
  return (
    <>
      <PageTitle title="Audit trail" subtitle="Append-only record of who did what and when. The database rejects edits and deletes. Secrets are redacted." />
      <div className="mb-4 max-w-xs">
        <Field label="Event type">
          <select className={inputClass} value={type} onChange={(e) => setType(e.target.value)}>
            {TYPES.map((t) => <option key={t} value={t}>{t ? label(t) : "All events"}</option>)}
          </select>
        </Field>
      </div>
      <Card padded={false}>
        <ErrorBox error={error} />
        {loading && !data ? <div className="p-4"><Loading rows={8} /></div> : data?.length === 0 ? <Empty title="No audit events" icon="audit" /> : (
          <ul className="divide-y divide-line">
            {data?.map((e) => (
              <li key={e.id} className="px-4 py-3">
                <details className="group">
                  <summary className="flex cursor-pointer list-none flex-wrap items-center gap-3 text-sm">
                    <span className="flex size-7 items-center justify-center rounded-full bg-subtle text-muted" title={e.actor_type}><Icon name={ACTOR[e.actor_type] ?? "user"} size={14} /></span>
                    <span className="font-medium text-ink">{label(e.event_type)}</span>
                    <span className="text-xs text-muted">{e.actor_type} · {e.actor_id.slice(0, 28)}</span>
                    {e.run_id && <Link href={`/runs/${e.run_id}`} className="font-mono text-xs text-accent" onClick={(ev) => ev.stopPropagation()}>run {e.run_id.slice(0, 8)}</Link>}
                    <span className="ml-auto text-xs text-muted" title={when(e.created_at)}>{relative(e.created_at)}</span>
                    <Icon name="chevron" className="text-muted transition group-open:rotate-90" />
                  </summary>
                  <pre className="mt-2 ml-10 overflow-x-auto rounded-md bg-subtle p-2 text-[11px] text-muted">{JSON.stringify(e.metadata, null, 2)}</pre>
                </details>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </>
  );
}
