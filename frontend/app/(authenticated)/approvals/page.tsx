"use client";
import { useMemo, useState } from "react";
import { useApi } from "@/lib/api";
import type { Approval } from "@/lib/types";
import { ApprovalGroup } from "@/components/approval-card";
import { Empty, ErrorBox, Loading, PageTitle, Segmented } from "@/components/ui";

type Filter = "pending" | "approved" | "rejected" | "expired" | "all";

export default function ApprovalsPage() {
  const [status, setStatus] = useState<Filter>("pending");
  const { data, error, loading, reload } = useApi<Approval[]>(`/api/v1/approvals${status === "all" ? "" : `?status=${status}`}`);

  const groups = useMemo(() => {
    const byRun = new Map<string, Approval[]>();
    for (const a of data ?? []) byRun.set(a.run_id, [...(byRun.get(a.run_id) ?? []), a]);
    // oldest request first: it expires soonest
    return [...byRun.values()]
      .map((g) => g.sort((x, y) => x.action_type.localeCompare(y.action_type)))
      .sort((a, b) => a[0]!.created_at.localeCompare(b[0]!.created_at));
  }, [data]);

  return (
    <>
      <PageTitle
        title="Approvals"
        subtitle="Each card is one investigation. Approve or reject the exact actions the agent proposed. An approval records its simulated effect exactly once."
        actions={
          <Segmented<Filter>
            ariaLabel="Filter approvals"
            value={status}
            onChange={setStatus}
            options={[
              { value: "pending", label: `Pending${status === "pending" && data ? ` · ${data.length}` : ""}` },
              { value: "approved", label: "Approved" },
              { value: "rejected", label: "Rejected" },
              { value: "expired", label: "Expired" },
              { value: "all", label: "All" },
            ]}
          />
        }
      />
      <ErrorBox error={error} />
      {loading && !data ? (
        <div className="rounded-xl border border-line bg-surface p-4"><Loading rows={6} /></div>
      ) : groups.length === 0 ? (
        <div className="rounded-xl border border-line bg-surface">
          <Empty title={status === "pending" ? "All caught up" : `No ${status} approvals`} icon="shield">
            {status === "pending" ? "New proposals from the agent appear here for review." : undefined}
          </Empty>
        </div>
      ) : (
        <div className="space-y-5">
          {groups.map((g) => <ApprovalGroup key={g[0]!.run_id} approvals={g} onDecided={() => void reload()} />)}
        </div>
      )}
    </>
  );
}
