"use client";
import { useState } from "react";
import { ActivityBars, DistributionBar, Meter, type Segment } from "@/components/charts";
import { Icon } from "@/components/icons";
import {
  Badge,
  Card,
  Empty,
  ErrorBox,
  Loading,
  PageTitle,
  Segmented,
  Skeleton,
  StatCard,
  type Tone,
} from "@/components/ui";
import { useApi } from "@/lib/api";
import { label, money } from "@/lib/format";
import type { Analytics, EvalReport } from "@/lib/types";

const WINDOWS = [
  { value: "24", label: "24h" },
  { value: "168", label: "7d" },
  { value: "720", label: "30d" },
  { value: "all", label: "All" },
] as const;
type WindowValue = (typeof WINDOWS)[number]["value"];

// Fixed outcome order + status tone. These are states (not categorical series), so color is
// reserved and always carries a text label.
const OUTCOME_ORDER: [string, Tone][] = [
  ["completed", "good"],
  ["no_action", "neutral"],
  ["needs_review", "warn"],
  ["rejected", "bad"],
  ["failed", "bad"],
  ["cancelled", "neutral"],
  ["active", "info"],
];

const pct = (n: number) => `${Math.round(n * 100)}%`;
const ms = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(1)} s` : `${n} ms`);

function errorRateTone(rate: number): Tone {
  if (rate === 0) return "good";
  if (rate < 0.1) return "warn";
  return "bad";
}

export default function AnalyticsPage() {
  const [win, setWin] = useState<WindowValue>("all");
  const query = win === "all" ? "" : `?window_hours=${win}`;
  const a = useApi<Analytics>(`/api/v1/analytics${query}`);
  const evalReport = useApi<EvalReport>("/api/v1/eval-report");
  const d = a.data;

  const segments: Segment[] = d
    ? OUTCOME_ORDER.filter(([k]) => (d.outcomes[k] ?? 0) > 0).map(([k, tone]) => ({
        label: label(k),
        value: d.outcomes[k] ?? 0,
        tone,
      }))
    : [];

  return (
    <>
      <PageTitle
        title="Agent analytics"
        subtitle="Measured cost, latency, reliability and safety of the investigation agent — nothing estimated from the model's own report."
        actions={<Segmented value={win} options={WINDOWS.map((w) => ({ value: w.value, label: w.label }))} onChange={setWin} ariaLabel="Time window" />}
      />
      <ErrorBox error={a.error} />

      {/* Headline metrics */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        {!d ? (
          Array.from({ length: 5 }, (_, i) => <Skeleton key={i} className="h-[86px] rounded-xl" />)
        ) : (
          <>
            <StatCard label="Investigations" value={d.runs_total} hint={d.runs_active ? `${d.runs_active} active now` : "all finished"} icon="sparkle" tone="info" />
            <StatCard label="Success rate" value={pct(d.success_rate)} hint={`${d.by_status.completed ?? 0}/${d.runs_finished} completed`} icon="check" tone={d.success_rate >= 0.5 ? "good" : "warn"} />
            <StatCard label="Agent latency p50" value={ms(d.latency.p50_ms)} hint={`p95 ${ms(d.latency.p95_ms)}`} icon="gauge" tone="neutral" />
            <StatCard label="Token spend" value={d.tokens_total.toLocaleString("en-IN")} hint={d.tokens_total === 0 ? "offline model" : `≈ $${d.est_cost_usd.toFixed(2)}${d.cost_complete ? "" : "+"}`} icon="coin" tone="neutral" />
            <StatCard label="Simulated effects" value={d.refunds + d.messages + d.escalations} hint={`${d.refunds} refunds · ${money(d.refund_total_minor)}`} icon="money" tone="good" />
          </>
        )}
      </div>

      <div className="mt-6 grid items-start gap-5 lg:grid-cols-2">
        <Card title="Run outcomes" icon="flag">
          {!d ? (
            <Loading />
          ) : (
            <>
              <DistributionBar segments={segments} />
              <div className="mt-5 grid grid-cols-3 gap-3 border-t border-line pt-4">
                {([
                  ["Refunds", d.refunds, money(d.refund_total_minor), "money" as const],
                  ["Replies sent", d.messages, "customers notified", "mail" as const],
                  ["Escalations", d.escalations, "to a human", "flag" as const],
                ] as const).map(([name, value, hint, icon]) => (
                  <div key={name}>
                    <div className="flex items-center gap-1.5 text-muted"><Icon name={icon} size={14} /><span className="text-xs">{name}</span></div>
                    <p className="mt-1 text-xl font-semibold tabular-nums text-ink">{value}</p>
                    <p className="text-xs text-muted">{hint}</p>
                  </div>
                ))}
              </div>
            </>
          )}
        </Card>
        <Card title="Activity (last 14 days)" icon="chart">
          {!d ? <Loading /> : <ActivityBars data={d.daily} />}
        </Card>
      </div>

      <div className="mt-5 grid items-start gap-5 lg:grid-cols-2">
        <Card title="Tool reliability" icon="wrench" padded={false}>
          {!d ? (
            <div className="p-4"><Loading /></div>
          ) : d.tools.length === 0 ? (
            <Empty title="No tool calls yet" icon="wrench">Read-tool latency and error rates appear once the agent runs.</Empty>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-line text-left text-xs text-muted">
                  <th className="px-4 py-2 font-medium">Tool</th>
                  <th className="px-4 py-2 text-right font-medium">Calls</th>
                  <th className="px-4 py-2 text-right font-medium">Errors</th>
                  <th className="px-4 py-2 text-right font-medium">p50</th>
                  <th className="px-4 py-2 text-right font-medium">p95</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {d.tools.map((t) => (
                  <tr key={t.tool}>
                    <td className="px-4 py-2.5 font-mono text-ink">{t.tool}</td>
                    <td className="px-4 py-2.5 text-right tabular-nums text-ink">{t.calls}</td>
                    <td className="px-4 py-2.5 text-right"><Badge kind={errorRateTone(t.error_rate)}>{t.errors === 0 ? "none" : `${t.errors} · ${pct(t.error_rate)}`}</Badge></td>
                    <td className="px-4 py-2.5 text-right tabular-nums text-muted">{ms(t.p50_ms)}</td>
                    <td className="px-4 py-2.5 text-right tabular-nums text-muted">{ms(t.p95_ms)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>

        <Card title="Model usage" icon="layers" padded={false}>
          {!d ? (
            <div className="p-4"><Loading /></div>
          ) : d.models.length === 0 ? (
            <Empty title="No model runs yet" icon="layers">Each investigation records the model, its tokens and latency.</Empty>
          ) : (
            <>
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-line text-left text-xs text-muted">
                    <th className="px-4 py-2 font-medium">Model</th>
                    <th className="px-4 py-2 text-right font-medium">Runs</th>
                    <th className="px-4 py-2 text-right font-medium">Tokens</th>
                    <th className="px-4 py-2 text-right font-medium">Avg latency</th>
                    <th className="px-4 py-2 text-right font-medium">Est. cost</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {d.models.map((m) => (
                    <tr key={m.model}>
                      <td className="px-4 py-2.5 font-mono text-ink">{m.model}</td>
                      <td className="px-4 py-2.5 text-right tabular-nums text-ink">{m.runs}</td>
                      <td className="px-4 py-2.5 text-right tabular-nums text-muted">{m.total_tokens.toLocaleString("en-IN")}</td>
                      <td className="px-4 py-2.5 text-right tabular-nums text-muted">{ms(m.avg_latency_ms)}</td>
                      <td className="px-4 py-2.5 text-right tabular-nums text-muted">{m.cost_known ? `$${m.est_cost_usd.toFixed(4)}` : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="border-t border-line px-4 py-2.5 text-xs text-muted">Cost is estimated from a static list price; offline models report no tokens.</p>
            </>
          )}
        </Card>
      </div>

      <div className="mt-5">
        <EvaluationCard report={evalReport.data} loading={evalReport.loading} />
      </div>
    </>
  );
}

function EvaluationCard({ report, loading }: { report: EvalReport | null; loading: boolean }) {
  if (loading && !report) return <Card title="Evaluation suite" icon="beaker"><Loading /></Card>;
  if (!report?.available || !report.data) {
    return (
      <Card title="Evaluation suite" icon="beaker">
        <Empty title="No evaluation report yet" icon="beaker">Run <code className="font-mono text-xs">make eval</code> to measure the full pipeline across the scenario suite.</Empty>
      </Card>
    );
  }
  const e = report.data;
  const m = e.metrics;
  const safety: [string, number][] = [
    ["Unapproved writes", m.unapproved_writes],
    ["Duplicate writes", m.duplicate_writes],
    ["Policy violations", m.policy_violations],
    ["Cross-tenant leaks", m.cross_tenant_leaks],
  ];
  const allPass = e.scenarios_passed === e.scenarios_total;
  return (
    <Card
      title="Evaluation suite"
      icon="beaker"
      actions={<Badge kind={allPass ? "good" : "warn"}>{e.scenarios_passed}/{e.scenarios_total} passing</Badge>}
    >
      <div className="grid gap-6 lg:grid-cols-[1fr_1.4fr]">
        <div>
          <div className="flex items-baseline gap-2">
            <span className="text-4xl font-semibold tabular-nums text-ink">{e.scenarios_passed}</span>
            <span className="text-lg text-muted">/ {e.scenarios_total} scenarios</span>
          </div>
          <p className="mt-1 text-sm text-muted">{e.model_label}</p>
          <div className="mt-4 grid grid-cols-2 gap-2">
            {safety.map(([name, value]) => (
              <div key={name} className={`rounded-lg border px-3 py-2 ${value === 0 ? "border-good/30 bg-good-soft" : "border-bad/30 bg-bad-soft"}`}>
                <div className="flex items-center gap-1.5 text-lg font-semibold tabular-nums text-ink">
                  <Icon name={value === 0 ? "shield" : "alert"} className={value === 0 ? "text-good" : "text-bad"} />
                  {value}
                </div>
                <p className="text-xs text-muted">{name}</p>
              </div>
            ))}
          </div>
          <p className="mt-3 text-xs text-muted">
            Agent latency p50 {m.latency_investigation_ms.p50} ms · execution p50 {m.latency_execution_ms.p50} ms · {e.wall_seconds}s wall time
          </p>
        </div>
        <div className="space-y-3">
          <p className="text-xs font-medium text-muted">By category</p>
          {Object.entries(e.categories).map(([name, c]) => (
            <Meter key={name} label={label(name)} value={c.passed} total={c.total} tone={c.passed === c.total ? "good" : "warn"} />
          ))}
          <div className="grid grid-cols-2 gap-x-6 gap-y-2 pt-1 text-sm">
            <Ratio label="Task completion" r={m.task_completion} />
            <Ratio label="Tool validity" r={{ passed: m.tool_validity.ok, total: m.tool_validity.total }} />
            <Ratio label="Adversarial contained" r={m.adversarial_contained} />
            <Ratio label="Fault recovery" r={m.recovery} />
          </div>
        </div>
      </div>
    </Card>
  );
}

function Ratio({ label: text, r }: { label: string; r: { passed?: number; total?: number } }) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <span className="text-muted">{text}</span>
      <span className="font-medium tabular-nums text-ink">{r.passed ?? 0}/{r.total ?? 0}</span>
    </div>
  );
}
