"use client";
import Link from "next/link";
import { useApi } from "@/lib/api";
import { money, relative, when } from "@/lib/format";
import type { Message, Refund } from "@/lib/types";
import { Icon } from "@/components/icons";
import { Badge, Card, Empty, ErrorBox, Loading, PageTitle, SimulatedTag, StatCard } from "@/components/ui";

export default function LedgerPage() {
  const refunds = useApi<Refund[]>("/api/v1/refunds");
  const messages = useApi<Message[]>("/api/v1/messages");
  const total = (refunds.data ?? []).reduce((sum, r) => sum + r.amount_minor, 0);
  const fromAgent = (refunds.data ?? []).filter((r) => r.action_id).length;

  return (
    <>
      <PageTitle title="Mock ledger" subtitle="Simulated effects recorded in PostgreSQL. No money moved and no email was sent." />
      <div className="mb-5 grid gap-3 sm:grid-cols-3">
        <StatCard label="Refunded (simulated)" value={money(total)} icon="money" tone="good" />
        <StatCard label="Refunds from approved agent actions" value={fromAgent} hint={`${(refunds.data?.length ?? 0) - fromAgent} pre-existing fixture`} icon="shield" />
        <StatCard label="Messages (simulated)" value={messages.data?.length ?? "—"} icon="mail" tone="info" />
      </div>
      <div className="space-y-5">
        <Card title={<span className="flex items-center gap-2">Refunds <SimulatedTag /></span>} icon="money" padded={false}>
          <ErrorBox error={refunds.error} />
          {refunds.loading && !refunds.data ? <div className="p-4"><Loading /></div> : refunds.data?.length === 0 ? <Empty title="No refunds yet" icon="money" /> : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[560px] text-left text-sm" data-testid="refunds-table">
                <thead className="border-b border-line text-xs text-muted">
                  <tr><th className="px-4 py-2.5 font-medium">Order</th><th className="px-4 py-2.5 font-medium">Amount</th><th className="px-4 py-2.5 font-medium">Status</th><th className="px-4 py-2.5 font-medium">Source</th><th className="px-4 py-2.5 font-medium">Recorded</th></tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {refunds.data?.map((r) => (
                    <tr key={r.refund_id}>
                      <td className="px-4 py-3 font-mono">{r.order_number}</td>
                      <td className="px-4 py-3 font-semibold tabular-nums">{money(r.amount_minor, r.currency)}</td>
                      <td className="px-4 py-3"><Badge value={r.status} /></td>
                      <td className="px-4 py-3 text-xs text-muted">{r.action_id ? <span className="flex items-center gap-1"><Icon name="shield" size={12} /> approved agent action</span> : "pre-existing fixture"}</td>
                      <td className="px-4 py-3 text-muted" title={when(r.created_at)}>{relative(r.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
        <Card title={<span className="flex items-center gap-2">Outbound messages <SimulatedTag /></span>} icon="mail" padded={false}>
          <ErrorBox error={messages.error} />
          {messages.loading && !messages.data ? <div className="p-4"><Loading /></div> : messages.data?.length === 0 ? <Empty title="No messages yet" icon="mail" /> : (
            <ul className="divide-y divide-line">
              {messages.data?.map((m) => (
                <li key={m.message_id} className="px-4 py-3 text-sm">
                  <div className="flex flex-wrap items-center gap-2">
                    <Link className="font-mono text-xs font-semibold text-accent" href={`/tickets/${m.ticket_number}`}>{m.ticket_number}</Link>
                    <span className="text-muted">to {m.destination}</span>
                    <Badge value={m.status} />
                    <span className="ml-auto text-xs text-muted" title={when(m.created_at)}>{relative(m.created_at)}</span>
                  </div>
                  <p className="mt-1.5 whitespace-pre-wrap text-ink">{m.body}</p>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </>
  );
}
