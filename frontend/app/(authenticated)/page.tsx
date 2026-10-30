"use client";
import Link from "next/link";
import { useApi } from "@/lib/api";
import { actionTitle, label, money, relative } from "@/lib/format";
import type { Approval, Overview, Page, Policy, Run, Ticket } from "@/lib/types";
import { DelayBadge } from "@/components/delay";
import { Icon, type IconName } from "@/components/icons";
import { Badge, ButtonLink, Card, Empty, ErrorBox, Loading, PageTitle, Skeleton, StatCard, StatusDot } from "@/components/ui";

const ACTIVE = ["queued", "running", "investigating", "validating", "awaiting_approval", "resuming", "executing"];

type Attention = { key: string; href: string; icon: IconName; tone: string; title: React.ReactNode; detail: React.ReactNode };

export default function OverviewPage() {
  const overview = useApi<Overview>("/api/v1/overview");
  const runs = useApi<Run[]>("/api/v1/runs?limit=8");
  const allRuns = useApi<Run[]>("/api/v1/runs?limit=200&top_level=false");
  const tickets = useApi<Page<Ticket>>("/api/v1/tickets?status=open&limit=20");
  const policy = useApi<Policy>("/api/v1/policies/active");
  const me = useApi<{ roles: string[]; username: string | null }>("/api/v1/me");
  const supervisor = !!me.data?.roles.some((r) => r === "supervisor" || r === "admin");
  const approvals = useApi<Approval[]>(supervisor ? "/api/v1/approvals?status=pending" : null);
  const o = overview.data;
  const threshold = policy.data?.min_delay_days;

  const attention: Attention[] = [];
  const pendingByRun = new Map<string, Approval[]>();
  for (const a of approvals.data ?? []) pendingByRun.set(a.run_id, [...(pendingByRun.get(a.run_id) ?? []), a]);
  for (const [runId, group] of pendingByRun) {
    const refund = group.find((a) => a.action_type === "refund");
    attention.push({
      key: `a-${runId}`, href: "/approvals", icon: "shield", tone: "bg-warn-soft text-warn",
      title: <>Approve {group.map((a) => actionTitle(a.action_type).toLowerCase()).join(" + ")} for <span className="font-mono">{group[0]!.ticket_number}</span></>,
      detail: <>{refund ? `${money(Number(refund.payload.amount_minor))} · ` : ""}expires {relative(group[0]!.expires_at)}</>,
    });
  }
  for (const r of runs.data ?? []) {
    if (r.status === "failed" || r.status === "needs_human_review") {
      attention.push({
        key: `r-${r.run_id}`, href: `/runs/${r.run_id}`, icon: "alert", tone: "bg-bad-soft text-bad",
        title: <>Run for <span className="font-mono">{r.ticket_number ?? "batch"}</span> {label(r.status)}</>,
        detail: r.error_code ? label(r.error_code) : relative(r.created_at),
      });
    }
  }
  const investigated = new Set((allRuns.data ?? []).map((r) => r.ticket_number));
  const overdue = (tickets.data?.items ?? []).filter((t) =>
    threshold != null && (t.days_past_promised_delivery ?? 0) >= threshold && t.order_payment_status === "paid" &&
    !t.order_refunded && !investigated.has(t.ticket_number));
  for (const t of overdue.slice(0, 4)) {
    attention.push({
      key: `t-${t.ticket_number}`, href: `/agent?ticket=${t.ticket_number}`, icon: "truck", tone: "bg-info-soft text-info",
      title: <><span className="font-mono">{t.ticket_number}</span> may qualify for a delay refund. Not investigated yet</>,
      detail: <>{t.subject} · {t.days_past_promised_delivery} d late</>,
    });
  }

  return (
    <>
      <PageTitle
        title={me.data?.username ? `Welcome back, ${me.data.username}` : "Overview"}
        subtitle="Your tenant's support queue and agent activity."
        actions={<ButtonLink href="/agent" icon="sparkle">New investigation</ButtonLink>}
      />
      <ErrorBox error={overview.error} />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        {!o ? Array.from({ length: 5 }, (_, i) => <Skeleton key={i} className="h-[86px] rounded-xl" />) : (
          <>
            <StatCard label="Open tickets" value={o.open_tickets} icon="ticket" tone="info" href="/tickets?status=open" />
            <StatCard label="High priority" value={o.high_priority_open_tickets} icon="alert" tone="warn" href="/tickets?status=open&priority=high" />
            <StatCard label="Pending approvals" value={o.pending_approvals} icon="shield" tone={o.pending_approvals ? "warn" : "neutral"} href={supervisor ? "/approvals" : undefined} />
            <StatCard label="Runs (24 h)" value={o.runs_today} icon="runs" href="/runs" />
            <StatCard label="Simulated refunds" value={money(o.simulated_refund_total_minor)} hint={`${o.simulated_refunds} refunds`} icon="money" tone="good" href="/ledger" />
          </>
        )}
      </div>

      <div className="mt-6 grid gap-5 lg:grid-cols-[3fr_2fr]">
        <Card title="Needs your attention" icon="flag" padded={false}>
          {runs.loading && !runs.data ? <div className="p-4"><Loading /></div> : attention.length === 0 ? (
            <Empty title="Nothing needs you right now">Pending approvals, failed runs and overdue orders show up here.</Empty>
          ) : (
            <ul className="divide-y divide-line">
              {attention.map((a) => (
                <li key={a.key}>
                  <Link href={a.href} className="flex items-center gap-3 px-4 py-3 hover:bg-subtle">
                    <span className={`flex size-8 shrink-0 items-center justify-center rounded-lg ${a.tone}`}><Icon name={a.icon} /></span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium text-ink">{a.title}</span>
                      <span className="block truncate text-xs text-muted">{a.detail}</span>
                    </span>
                    <Icon name="chevron" className="text-muted" />
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title="Recent runs" icon="runs" padded={false} actions={<Link href="/runs" className="text-xs text-accent hover:underline">View all</Link>}>
          <ErrorBox error={runs.error} />
          {runs.data?.length === 0 ? <Empty title="No runs yet" icon="runs">Start one from the agent console.</Empty> : (
            <ul className="divide-y divide-line">
              {runs.data?.map((r) => (
                <li key={r.run_id}>
                  <Link href={`/runs/${r.run_id}`} className="flex items-center gap-3 px-4 py-2.5 text-sm hover:bg-subtle">
                    <StatusDot value={r.status} pulse={ACTIVE.includes(r.status)} />
                    <span className="font-mono font-medium text-ink">{r.ticket_number ?? "batch"}</span>
                    <Badge value={r.status} />
                    <span className="ml-auto text-xs text-muted">{relative(r.created_at)}</span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
          {overdue.length > 0 && (
            <div className="border-t border-line px-4 py-3 text-xs text-muted">
              {overdue.length} uninvestigated paid order{overdue.length > 1 ? "s are" : " is"} past the {threshold}-day policy threshold{" "}
              <span className="inline-flex gap-1 align-middle">{overdue.slice(0, 3).map((t) => <DelayBadge key={t.ticket_number} days={t.days_past_promised_delivery} threshold={threshold} />)}</span>
            </div>
          )}
        </Card>
      </div>
    </>
  );
}
