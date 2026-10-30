import { redirect } from "next/navigation";
import { Icon } from "@/components/icons";
import { readSession } from "@/lib/session";

export const dynamic = "force-dynamic";

const ERRORS: Record<string, string> = {
  expired: "Your sign-in attempt expired. Please try again.",
  callback: "Sign-in failed. Check that Keycloak is running and try again.",
};

const ACCOUNTS = [
  ["operator", "operator-demo", "Starts investigations"],
  ["supervisor", "supervisor-demo", "Approves actions"],
  ["admin", "admin-demo", "Sees the audit trail"],
  ["globex-supervisor", "globex-demo", "Another tenant"],
];

export default async function LoginPage({ searchParams }: { searchParams: Promise<{ error?: string }> }) {
  if (await readSession()) redirect("/");
  const { error } = await searchParams;
  return (
    <main className="flex min-h-[calc(100vh-28px)] items-center justify-center px-4 py-10">
      <div className="w-full max-w-md">
        <div className="rounded-2xl border border-line bg-surface p-8 shadow-sm">
          <span className="flex size-11 items-center justify-center rounded-xl bg-accent text-on-accent"><Icon name="sparkle" size={22} /></span>
          <h1 className="mt-5 text-2xl font-semibold tracking-tight text-ink">Operations AI</h1>
          <p className="mt-2 text-sm leading-relaxed text-muted">
            An AI investigator for support operations. The agent reads and proposes; deterministic rules validate; a
            supervisor approves; each change is applied exactly once.
          </p>
          {error && <p role="alert" className="mt-4 rounded-lg bg-bad-soft px-3 py-2 text-sm text-bad">{ERRORS[error] ?? "Sign-in failed."}</p>}
          <a href="/api/auth/login" className="mt-6 flex w-full items-center justify-center gap-2 rounded-lg bg-accent px-3 py-2.5 text-sm font-medium text-on-accent shadow-sm hover:bg-accent/90">
            Sign in with Keycloak <Icon name="arrow" />
          </a>
        </div>
        <div className="mt-4 rounded-xl border border-dashed border-line px-5 py-4 text-xs text-muted">
          <p className="mb-2 font-medium text-ink">Local demo accounts (development only)</p>
          <table className="w-full">
            <tbody>
              {ACCOUNTS.map(([user, pass, what]) => (
                <tr key={user}><td className="py-0.5 pr-3 font-mono text-ink">{user}</td><td className="pr-3 font-mono">{pass}</td><td>{what}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </main>
  );
}
