"use client";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { AgentInput } from "@/components/agent-input";
import { Icon, type IconName } from "@/components/icons";
import { Card, Loading, PageTitle } from "@/components/ui";

const STEPS: [IconName, string, string][] = [
  ["wrench", "Investigate", "The agent reads the ticket, order, delivery events and refund policy through read-only MCP tools."],
  ["shield", "Validate", "The backend recomputes eligibility and the exact amount. The model's numbers are never trusted."],
  ["user", "Approve", "A supervisor approves or rejects each proposed action."],
  ["check", "Execute once", "An idempotent executor records the simulated refund or message exactly once."],
];

function AgentInner() {
  const params = useSearchParams();
  return (
    <>
      <PageTitle title="Agent console" subtitle="Ask the investigator to look into a ticket. You'll follow its tool calls live on the run page." />
      <div className="grid gap-5 lg:grid-cols-[3fr_2fr]">
        <Card title="New investigation" icon="sparkle">
          <AgentInput initialTicket={params.get("ticket") ?? undefined} />
        </Card>
        <Card title="How it works" icon="layers">
          <ol className="space-y-4">
            {STEPS.map(([icon, title, text], i) => (
              <li key={title} className="flex gap-3">
                <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-accent/10 text-accent"><Icon name={icon} /></span>
                <div>
                  <p className="text-sm font-medium text-ink">{i + 1}. {title}</p>
                  <p className="text-sm text-muted">{text}</p>
                </div>
              </li>
            ))}
          </ol>
        </Card>
      </div>
    </>
  );
}

export default function AgentPage() {
  return <Suspense fallback={<Loading />}><AgentInner /></Suspense>;
}
