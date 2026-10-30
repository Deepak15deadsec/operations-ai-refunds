"use client";
import Link from "next/link";
import { use } from "react";
import { useApi } from "@/lib/api";
import { relative } from "@/lib/format";
import type { OrderDetail, Policy, Run, TicketDetail } from "@/lib/types";
import { Icon } from "@/components/icons";
import { OrderDetails } from "@/components/order-details";
import { Avatar, Badge, ButtonLink, Card, Empty, ErrorBox, Loading, PageTitle, StatusDot } from "@/components/ui";

export default function TicketPage({ params }: { params: Promise<{ ticket: string }> }) {
  const { ticket } = use(params);
  const t = useApi<TicketDetail>(`/api/v1/tickets/${encodeURIComponent(ticket)}`);
  const order = useApi<OrderDetail>(t.data?.order_number ? `/api/v1/orders/${t.data.order_number}` : null);
  const policy = useApi<Policy>("/api/v1/policies/active");
  const runs = useApi<Run[]>("/api/v1/runs?limit=100&top_level=false");
  const history = (runs.data ?? []).filter((r) => r.ticket_number === ticket);

  if (t.loading && !t.data) return <Card><Loading rows={8} /></Card>;
  if (t.error) return <ErrorBox error={t.error} />;
  const data = t.data!;
  return (
    <>
      <PageTitle
        eyebrow={<Link href="/tickets" className="hover:text-ink">← Tickets</Link>}
        title={<span className="flex flex-wrap items-center gap-3"><span className="font-mono">{data.ticket_number}</span><span className="font-normal">{data.subject}</span></span>}
        subtitle={
          <span className="flex flex-wrap items-center gap-2">
            <Badge value={data.priority} /> <Badge value={data.status} />
            <span>opened {relative(data.created_at)} by {data.customer_name}</span>
          </span>
        }
        actions={<ButtonLink href={`/agent?ticket=${data.ticket_number}`} icon="sparkle">Investigate with agent</ButtonLink>}
      />
      <div className="grid gap-5 lg:grid-cols-[3fr_2fr]">
        <div className="space-y-5">
          <Card title="Customer message" icon="mail">
            <div className="flex gap-3">
              <Avatar name={data.customer_name} size={32} />
              <div className="min-w-0">
                <p className="text-sm font-medium text-ink">{data.customer_name}</p>
                <p className="mt-1 text-sm leading-relaxed whitespace-pre-wrap text-ink">{data.description}</p>
              </div>
            </div>
            <p className="mt-4 flex items-center gap-1.5 rounded-md bg-subtle px-2.5 py-1.5 text-xs text-muted">
              <Icon name="shield" size={12} /> The agent treats this text as untrusted data, never as instructions.
            </p>
          </Card>
          <Card title="Agent runs for this ticket" icon="runs" padded={false}>
            {history.length === 0 ? (
              <Empty title="Not investigated yet" icon="sparkle">Start an investigation to have the agent gather evidence and propose a resolution.</Empty>
            ) : (
              <ul className="divide-y divide-line">
                {history.map((r) => (
                  <li key={r.run_id}>
                    <Link href={`/runs/${r.run_id}`} className="flex items-center gap-3 px-4 py-2.5 text-sm hover:bg-subtle">
                      <StatusDot value={r.status} />
                      <Badge value={r.status} />
                      <span className="text-muted">by {r.requested_by_name ?? "unknown"}</span>
                      <span className="ml-auto text-xs text-muted">{relative(r.created_at)}</span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
        <Card title="Order" icon="truck">
          {!data.order_number ? (
            <p className="text-sm text-muted">No order is linked to this ticket.</p>
          ) : order.data ? (
            <OrderDetails order={order.data} events={order.data.delivery_events} threshold={policy.data?.min_delay_days} />
          ) : order.error ? <ErrorBox error={order.error} /> : <Loading rows={6} />}
        </Card>
      </div>
    </>
  );
}
