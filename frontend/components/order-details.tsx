import { day, money, when } from "@/lib/format";
import type { DeliveryEvent, Order } from "@/lib/types";
import { Icon } from "./icons";
import { Badge, KeyValue } from "./ui";

/** Order facts plus a delivery timeline with the promised date marked in place. */
export function OrderDetails({ order, events, threshold }: { order: Order; events?: DeliveryEvent[]; threshold?: number }) {
  const promised = new Date(order.promised_delivery_at).getTime();
  const undelivered = !order.actual_delivery_at && !["delivered", "cancelled"].includes(order.shipping_status);
  const daysLate = undelivered ? (Date.now() - promised) / 86_400_000 : 0;

  const timeline = [
    ...(events ?? []).map((e) => ({ ...e, marker: false })),
    { event_type: "promised_delivery", event_time: order.promised_delivery_at, description: "Promised delivery date", marker: true },
  ].sort((a, b) => a.event_time.localeCompare(b.event_time));

  return (
    <div className="space-y-5">
      {daysLate > 0 && (
        <div className={`flex items-start gap-3 rounded-lg px-3 py-2.5 text-sm ${threshold != null && daysLate >= threshold ? "bg-bad-soft text-bad" : "bg-warn-soft text-warn"}`}>
          <Icon name="truck" className="mt-0.5 shrink-0" />
          <div>
            <p className="font-semibold">{daysLate.toFixed(1)} days past promised delivery</p>
            {threshold != null && (
              <p className="text-xs opacity-90">
                {daysLate >= threshold
                  ? `Beyond the ${threshold}-day refund threshold.${order.refunded ? " Already refunded." : order.payment_status !== "paid" ? " Payment not completed." : ""}`
                  : `Refund threshold is ${threshold} days.`}
              </p>
            )}
          </div>
        </div>
      )}
      <KeyValue
        items={[
          ["Order", <span key="o" className="font-mono">{order.order_number}</span>],
          ["Total", <span key="t" className="font-semibold tabular-nums">{money(order.total_amount_minor, order.currency)}</span>],
          ["Payment", <Badge key="p" value={order.payment_status} />],
          ["Shipping", <Badge key="s" value={order.shipping_status} />],
          ["Promised", when(order.promised_delivery_at)],
          ["Delivered", when(order.actual_delivery_at)],
          ["Refunded", order.refunded ? <Badge key="r" kind="good">yes (simulated)</Badge> : "No"],
        ]}
      />
      {events && (
        <div>
          <h3 className="mb-3 text-xs font-semibold tracking-wide text-muted uppercase">Delivery history</h3>
          <ol className="relative space-y-3 before:absolute before:top-1.5 before:bottom-1.5 before:left-[5px] before:w-px before:bg-line">
            {timeline.map((e, i) => (
              <li key={i} className="relative flex gap-3 text-sm">
                <span className={`relative z-10 mt-1.5 size-[11px] shrink-0 rounded-full border-2 border-surface ${
                  e.marker ? "bg-warn" : e.event_type === "delivered" ? "bg-good" : e.event_type.includes("fail") || e.event_type.includes("delay") ? "bg-bad" : "bg-muted"
                }`} />
                <div className="min-w-0">
                  <p className={e.marker ? "font-medium text-warn" : "font-medium text-ink"}>
                    {e.event_type.replaceAll("_", " ")}
                    <span className="ml-2 text-xs font-normal text-muted">{day(e.event_time)}</span>
                  </p>
                  {!e.marker && <p className="text-muted">{e.description}</p>}
                </div>
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}
