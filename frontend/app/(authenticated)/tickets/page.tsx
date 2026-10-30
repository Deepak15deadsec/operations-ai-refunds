"use client";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { useApi } from "@/lib/api";
import type { Page, Policy, Ticket } from "@/lib/types";
import { Icon } from "@/components/icons";
import { TicketTable } from "@/components/ticket-table";
import { Button, Card, Empty, ErrorBox, inputClass, Loading, PageTitle, Segmented } from "@/components/ui";

function TicketsInner() {
  const router = useRouter();
  const params = useSearchParams();
  const [q, setQ] = useState(params.get("q") ?? "");
  const query = new URLSearchParams();
  for (const key of ["status", "priority", "q", "cursor"]) {
    const value = params.get(key);
    if (value) query.set(key, value);
  }
  query.set("limit", "20");
  const { data, error, loading } = useApi<Page<Ticket>>(`/api/v1/tickets?${query}`);
  const policy = useApi<Policy>("/api/v1/policies/active");

  const setParam = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value); else next.delete(key);
    next.delete("cursor");
    router.push(`/tickets?${next}`);
  };

  return (
    <>
      <PageTitle title="Tickets" subtitle="The support queue, with each order's delivery state at a glance." />
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <form className="relative min-w-60 flex-1 sm:max-w-sm" onSubmit={(e) => { e.preventDefault(); setParam("q", q); }}>
          <Icon name="search" className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-muted" />
          <input className={`${inputClass} w-full pl-9`} value={q} onChange={(e) => setQ(e.target.value)}
                 placeholder="Search subject or T-number" aria-label="Search tickets" />
        </form>
        <Segmented ariaLabel="Status" value={params.get("status") ?? ""} onChange={(v) => setParam("status", v)} options={[
          { value: "", label: "All" }, { value: "open", label: "Open" }, { value: "escalated", label: "Escalated" }, { value: "resolved", label: "Resolved" },
        ]} />
        <Segmented ariaLabel="Priority" value={params.get("priority") ?? ""} onChange={(v) => setParam("priority", v)} options={[
          { value: "", label: "Any priority" }, { value: "urgent", label: "Urgent" }, { value: "high", label: "High" }, { value: "medium", label: "Medium" }, { value: "low", label: "Low" },
        ]} />
      </div>
      <Card padded={false}>
        <ErrorBox error={error} />
        {loading && !data ? <div className="p-4"><Loading rows={8} /></div>
          : data && data.items.length === 0 ? <Empty title="No tickets match" icon="search">Try clearing a filter.</Empty>
          : data && <TicketTable tickets={data.items} threshold={policy.data?.min_delay_days} />}
        {data?.next_cursor && (
          <div className="border-t border-line p-3 text-right">
            <Button variant="secondary" onClick={() => setParam("cursor", data.next_cursor!)}>Next page</Button>
          </div>
        )}
      </Card>
      {policy.data && (
        <p className="mt-3 flex items-center gap-1.5 text-xs text-muted">
          <Icon name="truck" size={12} /> Red delay badges are past the {policy.data.min_delay_days}-day threshold of refund policy {policy.data.version}.
        </p>
      )}
    </>
  );
}

export default function TicketsPage() {
  return <Suspense fallback={<Loading />}><TicketsInner /></Suspense>;
}
