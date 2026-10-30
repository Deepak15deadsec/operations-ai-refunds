"use client";
import { useRouter } from "next/navigation";
import { money } from "@/lib/format";
import type { Ticket } from "@/lib/types";
import { DelayBadge } from "./delay";
import { Badge } from "./ui";

export function TicketTable({ tickets, threshold }: { tickets: Ticket[]; threshold?: number }) {
  const router = useRouter();
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[760px] text-left text-sm">
        <thead className="border-b border-line text-xs text-muted">
          <tr>
            <th className="px-4 py-2.5 font-medium">Ticket</th>
            <th className="px-4 py-2.5 font-medium">Customer</th>
            <th className="px-4 py-2.5 font-medium">Order</th>
            <th className="px-4 py-2.5 font-medium">Delivery</th>
            <th className="px-4 py-2.5 font-medium">Priority</th>
            <th className="px-4 py-2.5 font-medium">Status</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {tickets.map((t) => (
            <tr
              key={t.ticket_number}
              className="cursor-pointer hover:bg-subtle"
              onClick={() => router.push(`/tickets/${t.ticket_number}`)}
            >
              <td className="px-4 py-3">
                <a href={`/tickets/${t.ticket_number}`} className="font-mono text-xs font-semibold text-accent" onClick={(e) => e.stopPropagation()}>
                  {t.ticket_number}
                </a>
                <p className="mt-0.5 max-w-xs truncate text-ink">{t.subject}</p>
              </td>
              <td className="px-4 py-3 text-muted">{t.customer_name}</td>
              <td className="px-4 py-3">
                {t.order_number ? (
                  <>
                    <span className="font-mono text-xs text-muted">{t.order_number}</span>
                    <p className="tabular-nums text-ink">{money(t.order_total_minor)}</p>
                  </>
                ) : <span className="text-muted">—</span>}
              </td>
              <td className="px-4 py-3">
                <div className="flex flex-wrap gap-1">
                  {t.order_shipping_status && <Badge value={t.order_shipping_status} />}
                  {t.order_payment_status && t.order_payment_status !== "paid" && <Badge kind="bad">payment {t.order_payment_status}</Badge>}
                  <DelayBadge days={t.days_past_promised_delivery} threshold={threshold} />
                </div>
              </td>
              <td className="px-4 py-3"><Badge value={t.priority} /></td>
              <td className="px-4 py-3"><Badge value={t.status} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
