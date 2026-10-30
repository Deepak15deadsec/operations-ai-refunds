import Link from "next/link";
import { redirect } from "next/navigation";
import { Icon } from "@/components/icons";
import { Nav, type NavLink } from "@/components/nav";
import { ToastProvider } from "@/components/toast";
import { Avatar } from "@/components/ui";
import { hasRole, identityFrom, readSession } from "@/lib/session";

export const dynamic = "force-dynamic";

export default async function AuthenticatedLayout({ children }: { children: React.ReactNode }) {
  const identity = identityFrom(await readSession());
  if (!identity) redirect("/login");

  const links: NavLink[] = [
    { href: "/", label: "Overview", icon: "home" },
    { href: "/tickets", label: "Tickets", icon: "ticket" },
    { href: "/agent", label: "Agent console", icon: "sparkle" },
    { href: "/runs", label: "Runs", icon: "runs" },
    ...(hasRole(identity, "supervisor") ? [{ href: "/approvals", label: "Approvals", icon: "shield", badge: "approvals" } as NavLink] : []),
    { href: "/ledger", label: "Mock ledger", icon: "ledger" },
    ...(hasRole(identity, "admin") ? [{ href: "/audit", label: "Audit trail", icon: "audit" } as NavLink] : []),
  ];
  const role = identity.roles.includes("admin") ? "admin" : identity.roles.includes("supervisor") ? "supervisor" : "operator";

  const user = (primary: boolean) => (
    <div className="flex items-center gap-2.5">
      <Avatar name={identity.username} size={32} />
      <div className="min-w-0 text-sm leading-tight">
        <p className="truncate font-medium text-ink" data-testid={primary ? "whoami" : undefined}>{identity.username}</p>
        <p className="text-xs capitalize text-muted">{role}</p>
      </div>
      <form action="/api/auth/logout" method="post" className="ml-auto">
        <button className="rounded-md p-1.5 text-muted hover:bg-subtle hover:text-ink" aria-label="Sign out" title="Sign out">
          <Icon name="logout" />
        </button>
      </form>
    </div>
  );

  return (
    <ToastProvider>
      <div className="flex min-h-[calc(100vh-28px)]">
        <div className="hidden w-60 shrink-0 border-r border-line bg-surface md:block">
        <aside className="sticky top-0 flex h-screen flex-col px-3 py-4">
          <Link href="/" className="mb-6 flex items-center gap-2 px-2">
            <span className="flex size-8 items-center justify-center rounded-lg bg-accent text-on-accent"><Icon name="sparkle" size={18} /></span>
            <span className="font-semibold text-ink">Operations AI</span>
          </Link>
          <Nav links={links} />
          <div className="mt-auto border-t border-line pt-3">{user(true)}</div>
        </aside>
        </div>

        <div className="min-w-0 flex-1">
          <header className="border-b border-line bg-surface px-4 py-3 md:hidden">
            <div className="mb-2">{user(false)}</div>
            <Nav links={links} orientation="horizontal" />
          </header>
          <main className="mx-auto max-w-6xl px-4 py-6 md:px-8 md:py-8">{children}</main>
        </div>
      </div>
    </ToastProvider>
  );
}
