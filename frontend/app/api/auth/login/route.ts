import { NextRequest, NextResponse } from "next/server";
import { client, oidcConfig, redirectUri } from "@/lib/oidc";
import { LOGIN_COOKIE, seal } from "@/lib/session";

export const dynamic = "force-dynamic";

const safeNext = (value: string | null) => (value && value.startsWith("/") && !value.startsWith("//") ? value : "/");

export async function GET(req: NextRequest) {
  const verifier = client.randomPKCECodeVerifier();
  const state = client.randomState();
  const url = client.buildAuthorizationUrl(oidcConfig(), {
    redirect_uri: redirectUri(),
    scope: "openid profile",
    code_challenge: await client.calculatePKCECodeChallenge(verifier),
    code_challenge_method: "S256",
    state,
  });
  const res = NextResponse.redirect(url.href);
  res.cookies.set(LOGIN_COOKIE, await seal({ verifier, state, next: safeNext(req.nextUrl.searchParams.get("next")) }, 600), {
    httpOnly: true,
    sameSite: "lax",
    path: "/api/auth",
    maxAge: 600,
  });
  return res;
}
