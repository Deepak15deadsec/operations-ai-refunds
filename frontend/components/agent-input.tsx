"use client";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { api, ApiError, useApi } from "@/lib/api";
import { money } from "@/lib/format";
import type { Page, Policy, Ticket } from "@/lib/types";
import { DelayBadge } from "./delay";
import { Icon } from "./icons";
import { Badge, Button, ErrorBox, Field, inputClass, Segmented } from "./ui";

const PRESETS = [
  {
    label: "Resolve if eligible",
    text: "Investigate this ticket. Check the order and delivery history. If it qualifies under our refund policy, prepare a refund and a customer reply. Ask me to approve before taking any action.",
  },
  { label: "Status update only", text: "Investigate this ticket and draft a short status update for the customer. Do not propose a refund." },
  { label: "Escalate if unclear", text: "Investigate this ticket. If the facts are ambiguous or outside the refund policy, propose an escalation with a clear reason." },
];
const BATCH_PRESET = "Review open tickets about delayed deliveries and prepare recommended resolutions. Ask me to approve before taking any action.";

export function AgentInput({ initialTicket }: { initialTicket?: string }) {
  const router = useRouter();
  const tickets = useApi<Page<Ticket>>("/api/v1/tickets?limit=20");
  const policy = useApi<Policy>("/api/v1/policies/active");
  const [mode, setMode] = useState<"ticket" | "batch">("ticket");
  const [ticket, setTicket] = useState(initialTicket ?? "T-101");
  const [search, setSearch] = useState("");
  const [instruction, setInstruction] = useState(PRESETS[0]!.text);
  const [priority, setPriority] = useState("high");
  const [limit, setLimit] = useState(10);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const threshold = policy.data?.min_delay_days;

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return (tickets.data?.items ?? []).filter((t) => !q || t.ticket_number.toLowerCase().includes(q) || t.subject.toLowerCase().includes(q));
  }, [tickets.data, search]);
  const selected = tickets.data?.items.find((t) => t.ticket_number === ticket);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const body = mode === "ticket"
        ? { mode, ticket_number: ticket, instruction }
        : { mode, instruction, filters: { status: "open", priority }, limit };
      const res = await api<{ run_id: string }>("/api/v1/runs", { method: "POST", body: JSON.stringify(body) });
      router.push(`/runs/${res.run_id}`);
    } catch (err) {
      setError(err as ApiError);
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-5">
      <Segmented<"ticket" | "batch"> ariaLabel="Mode" value={mode} onChange={(m) => { setMode(m); setInstruction(m === "batch" ? BATCH_PRESET : PRESETS[0]!.text); }}
        options={[{ value: "ticket", label: "One ticket" }, { value: "batch", label: "Batch (max 10)" }]} />

      {mode === "ticket" ? (
        <div className="space-y-2">
          <p className="text-sm font-medium text-ink">Ticket</p>
          <div className="relative">
            <Icon name="search" className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-muted" />
            <input className={`${inputClass} w-full pl-9`} placeholder="Filter tickets…" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Filter tickets" />
          </div>
          <div role="radiogroup" aria-label="Ticket" className="max-h-64 divide-y divide-line overflow-y-auto rounded-lg border border-line">
            {filtered.map((t) => (
              <label key={t.ticket_number} className={`flex cursor-pointer items-center gap-3 px-3 py-2 text-sm ${ticket === t.ticket_number ? "bg-accent/10" : "hover:bg-subtle"}`}>
                <input type="radio" name="ticket" className="accent-[var(--accent)]" value={t.ticket_number} checked={ticket === t.ticket_number} onChange={() => setTicket(t.ticket_number)} />
                <span className="w-14 font-mono text-xs font-semibold text-ink">{t.ticket_number}</span>
                <span className="min-w-0 flex-1 truncate text-ink">{t.subject}</span>
                <DelayBadge days={t.days_past_promised_delivery} threshold={threshold} />
                <Badge value={t.priority} />
              </label>
            ))}
            {tickets.data && filtered.length === 0 && <p className="px-3 py-4 text-sm text-muted">No tickets match.</p>}
          </div>
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Open tickets with priority">
            <select className={inputClass} value={priority} onChange={(e) => setPriority(e.target.value)}>
              {["urgent", "high", "medium", "low"].map((p) => <option key={p}>{p}</option>)}
            </select>
          </Field>
          <Field label="Maximum tickets" hint="Each ticket gets its own run, approvals and failure isolation.">
            <input type="number" min={1} max={10} className={inputClass} value={limit} onChange={(e) => setLimit(Number(e.target.value))} />
          </Field>
        </div>
      )}

      <div className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-sm font-medium text-ink">Instruction</p>
          {mode === "ticket" && (
            <div className="flex flex-wrap gap-1.5">
              {PRESETS.map((p) => (
                <button key={p.label} type="button" onClick={() => setInstruction(p.text)}
                        className={`rounded-full border px-2.5 py-1 text-xs transition ${instruction === p.text ? "border-accent bg-accent/10 text-accent" : "border-line text-muted hover:text-ink"}`}>
                  {p.label}
                </button>
              ))}
            </div>
          )}
        </div>
        <textarea className={`${inputClass} min-h-28 w-full`} value={instruction} onChange={(e) => setInstruction(e.target.value)} maxLength={2000} required aria-label="Instruction" />
      </div>

      {mode === "ticket" && selected && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg bg-subtle px-3 py-2.5 text-sm">
          <Icon name="ticket" className="text-muted" />
          <span className="font-mono font-semibold">{selected.ticket_number}</span>
          <span className="text-muted">·</span>
          <span className="text-ink">{selected.customer_name}</span>
          {selected.order_number && <><span className="text-muted">·</span><span className="font-mono text-xs">{selected.order_number}</span><span>{money(selected.order_total_minor)}</span></>}
          {selected.order_shipping_status && <Badge value={selected.order_shipping_status} />}
          <DelayBadge days={selected.days_past_promised_delivery} threshold={threshold} />
        </div>
      )}

      <ErrorBox error={error} />
      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" icon="play" disabled={busy}>{busy ? "Starting…" : "Start investigation"}</Button>
        <p className="text-xs text-muted">Read-only. Nothing happens without a supervisor&apos;s approval.</p>
      </div>
    </form>
  );
}
