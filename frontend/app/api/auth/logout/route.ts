import { NextResponse } from "next/server";
import { appUrl, client, oidcConfig } from "@/lib/oidc";
import { clearSession } from "@/lib/session";

export const dynamic = "force-dynamic";

export async function POST() {
  await clearSession();
  const config = oidcConfig();
  const url = client.buildEndSessionUrl(config, {
    client_id: config.clientMetadata().client_id,
    post_logout_redirect_uri: `${appUrl()}/login`,
  });
  return NextResponse.redirect(url.href, { status: 303 });
}
