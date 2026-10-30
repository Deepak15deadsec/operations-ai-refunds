"use client";
import Link from "next/link";
import { useState } from "react";
import { useApi } from "@/lib/api";
import { duration, label, relative } from "@/lib/format";
import type { Run } from "@/lib/types";
import { Icon } from "@/components/icons";
import { Avatar, Badge, ButtonLink, Card, Empty, ErrorBox, Loading, PageTitle, Segmented, StatusDot } from "@/components/ui";

type Filter = "all" | "active" | "attention" | "done";
const ACTIVE = ["queued", "running", "investigating", "validating", "awaiting_approval", "resuming", "executing"];
const ATTENTION = ["awaiting_approval", "failed", "needs_human_review"];
const matches = (r: Run, f: Filter) =>
  f === "all" ? true : f === "active" ? ACTIVE.includes(r.status) : f === "attention" ? ATTENTION.includes(r.status) : !ACTIVE.includes(r.status);

export default function RunsPage() {
  const { data, error, loading } = useApi<Run[]>("/api/v1/runs?limit=100");
  const [filter, setFilter] = useState<Filter>("all");
  const rows = (data ?? []).filter((r) => matches(r, filter));
  const count = (f: Filter) => (data ?? []).filter((r) => matches(r, f)).length;

  return (
    <>
      <PageTitle
        title="Runs"
        subtitle="Durable history of every investigation, its approvals and outcome."
        actions={<ButtonLink href="/agent" icon="sparkle">New investigation</ButtonLink>}
      />
      <div className="mb-4">
        <Segmented<Filter> ariaLabel="Filter runs" value={filter} onChange={setFilter} options={[
          { value: "all", label: `All${data ? ` · ${count("all")}` : ""}` },
          { value: "active", label: `In progress${data ? ` · ${count("active")}` : ""}` },
          { value: "attention", label: `Needs attention${data ? ` · ${count("attention")}` : ""}` },
          { value: "done", label: "Finished" },
        ]} />
      </div>
      <Card padded={false}>
        <ErrorBox error={error} />
        {loading && !data ? <div className="p-4"><Loading rows={6} /></div> : rows.length === 0 ? (
          <Empty title="No runs here" icon="runs">Start an investigation from the agent console.</Empty>
        ) : (
          <ul className="divide-y divide-line">
            {rows.map((r) => (
              <li key={r.run_id}>
                <Link href={`/runs/${r.run_id}`} className="grid grid-cols-[auto_1fr_auto] items-center gap-x-4 gap-y-1 px-4 py-3 hover:bg-subtle sm:grid-cols-[auto_8rem_1fr_9rem_6rem_auto]">
                  <StatusDot value={r.status} pulse={ACTIVE.includes(r.status)} />
                  <span className="font-mono text-sm font-medium text-ink">{r.mode === "batch" ? <span className="flex items-center gap-1.5"><Icon name="layers" /> Batch</span> : r.ticket_number}</span>
                  <span className="hidden min-w-0 truncate text-sm text-muted sm:block">{r.original_instruction}</span>
                  <span className="hidden items-center gap-1.5 text-xs text-muted sm:flex"><Avatar name={r.requested_by_name} size={18} />{r.requested_by_name ?? "—"}</span>
                  <span className="hidden text-xs text-muted tabular-nums sm:block">{duration(r.started_at, r.finished_at)}</span>
                  <span className="flex items-center justify-end gap-3">
                    {r.error_code ? <Badge kind="bad">{label(r.error_code)}</Badge> : <Badge value={r.status} />}
                    <span className="w-16 text-right text-xs text-muted">{relative(r.created_at)}</span>
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </>
  );
}
