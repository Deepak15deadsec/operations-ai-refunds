"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import type { Overview } from "@/lib/types";
import { Icon, type IconName } from "./icons";
import { APPROVALS_CHANGED } from "./toast";

export type NavLink = { href: string; label: string; icon: IconName; badge?: "approvals" };

function usePendingApprovals(enabled: boolean) {
  const [count, setCount] = useState<number | null>(null);
  useEffect(() => {
    if (!enabled) return;
    let alive = true;
    const load = async () => {
      try {
        const res = await fetch("/api/proxy/api/v1/overview", { cache: "no-store" });
        if (res.ok && alive) setCount(((await res.json()) as Overview).pending_approvals);
      } catch {
        /* badge is best-effort */
      }
    };
    void load();
    const timer = setInterval(load, 15000);
    window.addEventListener(APPROVALS_CHANGED, load);
    return () => {
      alive = false;
      clearInterval(timer);
      window.removeEventListener(APPROVALS_CHANGED, load);
    };
  }, [enabled]);
  return count;
}

export function Nav({ links, orientation = "vertical" }: { links: NavLink[]; orientation?: "vertical" | "horizontal" }) {
  const pathname = usePathname();
  const pending = usePendingApprovals(links.some((l) => l.badge === "approvals"));
  const vertical = orientation === "vertical";
  return (
    <nav aria-label="Main" className={vertical ? "flex flex-col gap-0.5" : "flex gap-1 overflow-x-auto"}>
      {links.map((l) => {
        const active = l.href === "/" ? pathname === "/" : pathname.startsWith(l.href);
        return (
          <Link
            key={l.href}
            href={l.href}
            aria-current={active ? "page" : undefined}
            className={`group flex items-center gap-2.5 whitespace-nowrap rounded-lg px-3 py-2 text-sm transition ${
              active ? "bg-accent/10 font-medium text-accent" : "text-muted hover:bg-subtle hover:text-ink"
            }`}
          >
            <Icon name={l.icon} className={active ? "text-accent" : "text-muted group-hover:text-ink"} />
            <span>{l.label}</span>
            {l.badge === "approvals" && pending ? (
              <span className="ml-auto rounded-full bg-warn px-1.5 py-px text-[11px] font-semibold text-on-accent tabular-nums" data-testid={vertical ? "pending-badge" : undefined}>
                {pending}
              </span>
            ) : null}
          </Link>
        );
      })}
    </nav>
  );
}
