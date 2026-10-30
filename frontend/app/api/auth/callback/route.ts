import { NextRequest, NextResponse } from "next/server";
import { appUrl, client, oidcConfig } from "@/lib/oidc";
import { LOGIN_COOKIE, unseal, writeSession } from "@/lib/session";

export const dynamic = "force-dynamic";

type LoginState = { verifier: string; state: string; next: string };

export async function GET(req: NextRequest) {
  const login = await unseal<LoginState>(req.cookies.get(LOGIN_COOKIE)?.value);
  if (!login) return NextResponse.redirect(`${appUrl()}/login?error=expired`);
  // Rebuild the callback URL from the configured public origin (the container sees its own host).
  const current = new URL(`${appUrl()}/api/auth/callback${req.nextUrl.search}`);
  try {
    const tokens = await client.authorizationCodeGrant(oidcConfig(), current, {
      pkceCodeVerifier: login.verifier,
      expectedState: login.state,
    });
    await writeSession({
      access_token: tokens.access_token,
      refresh_token: tokens.refresh_token,
      expires_in: tokens.expires_in,
    });
  } catch (error) {
    console.error("OIDC callback failed", error instanceof Error ? error.message : error);
    return NextResponse.redirect(`${appUrl()}/login?error=callback`);
  }
  const res = NextResponse.redirect(`${appUrl()}${login.next}`);
  res.cookies.delete({ name: LOGIN_COOKIE, path: "/api/auth" });
  return res;
}
