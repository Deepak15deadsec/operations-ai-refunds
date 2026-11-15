"use client";
import type { ReactNode } from "react";
import type { Tone } from "./ui";

// Status/semantic fills — these encode state (outcome, pass/fail), always paired with a text label,
// never color alone. Reuses the app's validated design tokens.
const fill: Record<Tone, string> = {
  good: "bg-good",
  warn: "bg-warn",
  bad: "bg-bad",
  info: "bg-info",
  neutral: "bg-muted/60",
};
const dotFill: Record<Tone, string> = {
  good: "bg-good",
  warn: "bg-warn",
  bad: "bg-bad",
  info: "bg-info",
  neutral: "bg-muted",
};

export type Segment = { label: string; value: number; tone: Tone };

/** Horizontal part-to-whole bar: 2px gaps between segments, rounded outer ends, hover titles,
 *  with a labelled legend below so identity never rests on color. */
export function DistributionBar({ segments }: { segments: Segment[] }) {
  const shown = segments.filter((s) => s.value > 0);
  const total = shown.reduce((sum, s) => sum + s.value, 0);
  if (total === 0) return <p className="py-6 text-center text-sm text-muted">No runs in this window yet.</p>;
  return (
    <div>
      <div className="flex h-3 gap-0.5 overflow-hidden rounded-full" role="img" aria-label="Run outcomes">
        {shown.map((s) => (
          <div
            key={s.label}
            className={`${fill[s.tone]} first:rounded-l-full last:rounded-r-full`}
            style={{ width: `${(s.value / total) * 100}%` }}
            title={`${s.label}: ${s.value} (${Math.round((s.value / total) * 100)}%)`}
          />
        ))}
      </div>
      <ul className="mt-4 grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-3">
        {segments.map((s) => (
          <li key={s.label} className="flex items-center gap-2 text-sm">
            <span className={`size-2.5 shrink-0 rounded-full ${dotFill[s.tone]}`} />
            <span className="text-muted">{s.label}</span>
            <span className="ml-auto font-medium tabular-nums text-ink">{s.value}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export type DayDatum = { date: string; runs: number; completed: number };

/** 14-day activity: one bar per day (total runs), with the completed share drawn darker.
 *  Two series -> a legend is present; each bar has a hover tooltip. */
export function ActivityBars({ data }: { data: DayDatum[] }) {
  const max = Math.max(1, ...data.map((d) => d.runs));
  const fmt = (iso: string) => new Date(iso + "T00:00:00Z").toLocaleDateString("en-IN", { day: "numeric", month: "short" });
  const total = data.reduce((s, d) => s + d.runs, 0);
  if (total === 0) return <p className="py-6 text-center text-sm text-muted">No activity in this window yet.</p>;
  return (
    <div>
      <div className="flex h-32 items-end gap-1" role="img" aria-label="Runs per day">
        {data.map((d) => (
          <div key={d.date} className="group relative flex h-full flex-1 flex-col justify-end" title={`${fmt(d.date)}: ${d.runs} run${d.runs === 1 ? "" : "s"}, ${d.completed} completed`}>
            <div className="flex w-full flex-col justify-end rounded-t bg-accent/25" style={{ height: `${(d.runs / max) * 100}%`, minHeight: d.runs ? 3 : 0 }}>
              <div className="w-full rounded-t bg-accent" style={{ height: `${d.runs ? (d.completed / d.runs) * 100 : 0}%` }} />
            </div>
          </div>
        ))}
      </div>
      <div className="mt-2 flex justify-between text-xs text-muted">
        <span>{fmt(data[0]!.date)}</span>
        <span>{fmt(data[data.length - 1]!.date)}</span>
      </div>
      <div className="mt-3 flex gap-4 text-xs text-muted">
        <span className="flex items-center gap-1.5"><span className="size-2.5 rounded-sm bg-accent" /> Completed</span>
        <span className="flex items-center gap-1.5"><span className="size-2.5 rounded-sm bg-accent/25" /> Other outcomes</span>
      </div>
    </div>
  );
}

/** Thin labelled meter (passed / total), rounded end, for eval category pass rates. */
export function Meter({ label, value, total, tone = "good", suffix }: {
  label: ReactNode; value: number; total: number; tone?: Tone; suffix?: ReactNode;
}) {
  const pct = total ? (value / total) * 100 : 0;
  return (
    <div className="text-sm">
      <div className="mb-1 flex items-baseline justify-between gap-2">
        <span className="text-muted">{label}</span>
        <span className="font-medium tabular-nums text-ink">{suffix ?? `${value}/${total}`}</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-subtle">
        <div className={`h-full rounded-full ${fill[tone]}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}
