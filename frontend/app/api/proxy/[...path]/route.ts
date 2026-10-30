import { NextRequest, NextResponse } from "next/server";
import { appUrl } from "@/lib/oidc";
import { freshSession } from "@/lib/session";

/**
 * Same-origin proxy to the FastAPI backend. Attaches the bearer token server-side, so the browser
 * (including native EventSource for SSE) authenticates with the httpOnly session cookie only.
 */
export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const API = (process.env.API_INTERNAL_URL ?? "http://localhost:8000").replace(/\/$/, "");
const FORWARD_HEADERS = ["content-type", "last-event-id", "x-request-id"];

async function forward(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  if (path[0] !== "api" || path[1] !== "v1" || path.some((p) => p === ".." || p.includes("/"))) {
    return NextResponse.json({ error_code: "not_found", message: "Not found" }, { status: 404 });
  }
  if (req.method !== "GET") {
    // CSRF defence in addition to SameSite=Lax: state-changing calls must come from our own origin.
    const origin = req.headers.get("origin");
    if (!origin || origin !== new URL(appUrl()).origin) {
      return NextResponse.json({ error_code: "forbidden", message: "Cross-origin request refused" }, { status: 403 });
    }
  }
  const session = await freshSession();
  if (!session) {
    return NextResponse.json({ error_code: "unauthenticated", message: "Please sign in" }, { status: 401 });
  }
  const headers = new Headers({ Authorization: `Bearer ${session.at}` });
  for (const name of FORWARD_HEADERS) {
    const value = req.headers.get(name);
    if (value) headers.set(name, value);
  }
  const upstream = await fetch(`${API}/${path.join("/")}${req.nextUrl.search}`, {
    method: req.method,
    headers,
    body: req.method === "GET" ? undefined : await req.text(),
    cache: "no-store",
    signal: req.signal,
  });
  const out = new Headers();
  for (const name of ["content-type", "cache-control", "x-request-id"]) {
    const value = upstream.headers.get(name);
    if (value) out.set(name, value);
  }
  if (out.get("content-type")?.startsWith("text/event-stream")) out.set("X-Accel-Buffering", "no");
  return new Response(upstream.body, { status: upstream.status, headers: out });
}

export { forward as GET, forward as POST };
