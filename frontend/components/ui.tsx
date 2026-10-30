import Link from "next/link";
import type { ReactNode } from "react";
import { initials, label } from "@/lib/format";
import { Icon, type IconName } from "./icons";

export function Card({ title, icon, actions, children, className = "", padded = true }: {
  title?: ReactNode; icon?: IconName; actions?: ReactNode; children: ReactNode; className?: string; padded?: boolean;
}) {
  return (
    <section className={`rounded-xl border border-line bg-surface shadow-[0_1px_2px_rgba(0,0,0,0.04)] ${className}`}>
      {(title || actions) && (
        <header className="flex items-center justify-between gap-3 border-b border-line px-4 py-3">
          {title && (
            <h2 className="flex items-center gap-2 text-sm font-semibold text-ink">
              {icon && <Icon name={icon} className="text-muted" />}
              {title}
            </h2>
          )}
          {actions}
        </header>
      )}
      <div className={padded ? "p-4" : ""}>{children}</div>
    </section>
  );
}

export function PageTitle({ title, subtitle, actions, eyebrow }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode; eyebrow?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        {eyebrow && <div className="mb-1 text-xs font-medium text-muted">{eyebrow}</div>}
        <h1 className="text-2xl font-semibold tracking-tight text-ink">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}

const tone = {
  good: "bg-good-soft text-good",
  warn: "bg-warn-soft text-warn",
  bad: "bg-bad-soft text-bad",
  info: "bg-info-soft text-info",
  neutral: "bg-subtle text-muted",
} as const;
export type Tone = keyof typeof tone;

const statusTone: Record<string, Tone> = {
  completed: "good", approved: "good", simulated_success: "good", simulated_sent: "good", resolved: "good", paid: "good",
  delivered: "good",
  awaiting_approval: "warn", pending_approval: "warn", pending: "warn", needs_review: "warn", in_transit: "info",
  needs_human_review: "warn", escalated: "warn", delayed: "warn", medium: "neutral",
  failed: "bad", rejected: "bad", expired: "bad", cancelled: "bad", urgent: "bad",
  running: "info", investigating: "info", validating: "info", executing: "info", resuming: "info", queued: "info",
  open: "info", high: "warn", completed_no_action: "neutral",
};

export const toneFor = (value: string): Tone => statusTone[value] ?? "neutral";

export function Badge({ value, kind, children }: { value?: string; kind?: Tone; children?: ReactNode }) {
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap ${tone[kind ?? toneFor(value ?? "")]}`}>
      {children ?? label(value ?? "")}
    </span>
  );
}

const dot: Record<Tone, string> = { good: "bg-good", warn: "bg-warn", bad: "bg-bad", info: "bg-info", neutral: "bg-muted" };
export function StatusDot({ value, pulse }: { value: string; pulse?: boolean }) {
  const t = toneFor(value);
  return (
    <span className="relative inline-flex size-2.5 shrink-0">
      {pulse && <span className={`absolute inline-flex size-full animate-ping rounded-full opacity-60 ${dot[t]}`} />}
      <span className={`relative inline-flex size-2.5 rounded-full ${dot[t]}`} />
    </span>
  );
}

export function SimulatedTag() {
  return <span className="rounded border border-warn/60 px-1.5 py-px text-[10px] font-bold tracking-wider text-warn">SIMULATED</span>;
}

type ButtonVariant = "primary" | "secondary" | "danger" | "ghost";
const buttonStyles: Record<ButtonVariant, string> = {
  primary: "bg-accent text-on-accent hover:bg-accent/90 shadow-sm",
  secondary: "border border-line bg-surface text-ink hover:bg-subtle",
  danger: "border border-bad/40 bg-surface text-bad hover:bg-bad-soft",
  ghost: "text-muted hover:bg-subtle hover:text-ink",
};

export function Button({ children, variant = "primary", icon, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant; icon?: IconName }) {
  return (
    <button
      {...props}
      className={`inline-flex items-center justify-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-50 ${buttonStyles[variant]} ${props.className ?? ""}`}
    >
      {icon && <Icon name={icon} />}
      {children}
    </button>
  );
}

export function ButtonLink({ href, children, variant = "primary", icon }: { href: string; children: ReactNode; variant?: ButtonVariant; icon?: IconName }) {
  return (
    <Link href={href} className={`inline-flex items-center justify-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium transition ${buttonStyles[variant]}`}>
      {icon && <Icon name={icon} />}
      {children}
    </Link>
  );
}

export function ErrorBox({ error }: { error: { message: string; code?: string } | null }) {
  if (!error) return null;
  return (
    <div role="alert" className="flex items-start gap-2 rounded-lg border border-bad/30 bg-bad-soft px-3 py-2 text-sm text-bad">
      <Icon name="alert" className="mt-0.5 shrink-0" />
      <span>
        {error.message}
        {error.code && <span className="ml-2 font-mono text-xs opacity-75">({error.code})</span>}
      </span>
    </div>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded-md bg-subtle ${className}`} aria-hidden="true" />;
}

export function Loading({ rows = 4 }: { rows?: number }) {
  return (
    <div className="space-y-3 py-2" aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className={`h-4 ${i % 3 === 2 ? "w-2/3" : "w-full"}`} />
      ))}
    </div>
  );
}

export function Empty({ icon = "check", title, children }: { icon?: IconName; title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-10 text-center">
      <span className="flex size-10 items-center justify-center rounded-full bg-subtle text-muted"><Icon name={icon} size={18} /></span>
      <p className="text-sm font-medium text-ink">{title}</p>
      {children && <p className="max-w-sm text-sm text-muted">{children}</p>}
    </div>
  );
}

export function Field({ label: text, children, hint }: { label: string; children: ReactNode; hint?: ReactNode }) {
  return (
    <label className="flex flex-col gap-1.5 text-sm">
      <span className="font-medium text-ink">{text}</span>
      {children}
      {hint && <span className="text-xs text-muted">{hint}</span>}
    </label>
  );
}

export const inputClass =
  "rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink placeholder:text-muted/70 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20";

export function KeyValue({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[max-content_1fr] gap-x-6 gap-y-2.5 text-sm">
      {items.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-muted">{k}</dt>
          <dd className="min-w-0 break-words text-ink">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

export function StatCard({ label: text, value, hint, icon, href, tone: t = "neutral" }: {
  label: string; value: ReactNode; hint?: ReactNode; icon: IconName; href?: string; tone?: Tone;
}) {
  const body = (
    <div className="flex h-full items-start gap-3 rounded-xl border border-line bg-surface p-4 transition hover:border-accent/40 hover:shadow-sm">
      <span className={`flex size-9 shrink-0 items-center justify-center rounded-lg ${tone[t]}`}><Icon name={icon} size={18} /></span>
      <div className="min-w-0">
        <p className="text-xs font-medium text-muted">{text}</p>
        <p className="mt-0.5 text-xl font-semibold tabular-nums text-ink">{value}</p>
        {hint && <p className="mt-0.5 text-xs text-muted">{hint}</p>}
      </div>
    </div>
  );
  return href ? <Link href={href} className="block">{body}</Link> : body;
}

export function Avatar({ name, size = 28 }: { name: string | null | undefined; size?: number }) {
  return (
    <span
      className="inline-flex shrink-0 items-center justify-center rounded-full bg-accent/15 text-[11px] font-semibold text-accent"
      style={{ width: size, height: size }}
      aria-hidden="true"
    >
      {initials(name)}
    </span>
  );
}

export function Segmented<T extends string>({ value, options, onChange, ariaLabel }: {
  value: T; options: { value: T; label: ReactNode }[]; onChange: (v: T) => void; ariaLabel: string;
}) {
  return (
    <div role="tablist" aria-label={ariaLabel} className="inline-flex max-w-full overflow-x-auto rounded-lg border border-line bg-subtle p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="tab"
          aria-selected={value === o.value}
          onClick={() => onChange(o.value)}
          className={`rounded-md px-3 py-1.5 text-sm whitespace-nowrap transition ${value === o.value ? "bg-surface font-medium text-ink shadow-sm" : "text-muted hover:text-ink"}`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
