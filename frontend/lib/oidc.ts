import "server-only";
import * as client from "openid-client";

/**
 * The browser reaches Keycloak at the public URL (localhost); this server reaches it at the internal
 * Compose URL. Endpoints are configured explicitly instead of via discovery, because discovery would
 * return public URLs that are unreachable from inside the container. Tokens carry the public issuer,
 * which is what we validate against.
 */
const env = (name: string, fallback?: string) => {
  const value = process.env[name] ?? fallback;
  if (!value) throw new Error(`${name} is not configured`);
  return value;
};

let cached: client.Configuration | null = null;

export function appUrl(): string {
  return env("APP_URL", "http://localhost:3000").replace(/\/$/, "");
}

export function oidcConfig(): client.Configuration {
  if (cached) return cached;
  const publicIssuer = env("OIDC_PUBLIC_ISSUER");
  const internal = env("OIDC_INTERNAL_ISSUER", publicIssuer);
  const metadata: client.ServerMetadata = {
    issuer: publicIssuer,
    authorization_endpoint: `${publicIssuer}/protocol/openid-connect/auth`,
    end_session_endpoint: `${publicIssuer}/protocol/openid-connect/logout`,
    token_endpoint: `${internal}/protocol/openid-connect/token`,
    jwks_uri: `${internal}/protocol/openid-connect/certs`,
    userinfo_endpoint: `${internal}/protocol/openid-connect/userinfo`,
    id_token_signing_alg_values_supported: ["RS256"],
  };
  const config = new client.Configuration(metadata, env("OIDC_CLIENT_ID"), env("OIDC_CLIENT_SECRET"));
  if (publicIssuer.startsWith("http://") || internal.startsWith("http://")) {
    // Local demo only: Keycloak runs over plain HTTP inside Docker.
    client.allowInsecureRequests(config);
  }
  cached = config;
  return config;
}

export const redirectUri = () => `${appUrl()}/api/auth/callback`;
export { client };
