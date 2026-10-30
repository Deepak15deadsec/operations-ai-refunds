import { Icon } from "./icons";

/** How late an undelivered order is, coloured against the refund-policy threshold. */
export function DelayBadge({ days, threshold }: { days: number | null | undefined; threshold?: number }) {
  if (days == null) return null;
  const overThreshold = threshold != null && days >= threshold;
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium tabular-nums whitespace-nowrap ${
        overThreshold ? "bg-bad-soft text-bad" : "bg-warn-soft text-warn"
      }`}
      title={threshold != null ? `Refund policy threshold: ${threshold} days` : undefined}
    >
      <Icon name="truck" size={12} />
      {days.toFixed(days < 10 ? 1 : 0)} d late
    </span>
  );
}
