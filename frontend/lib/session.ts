import "server-only";
import { cookies } from "next/headers";
import { EncryptJWT, jwtDecrypt } from "jose";
import { client, oidcConfig } from "./oidc";

/**
 * Backend-for-frontend session: tokens live only in an encrypted, httpOnly cookie. The browser never
 * sees an access token; it calls /api/proxy, which attaches the bearer token server-side.
 */
export const SESSION_COOKIE = "ops_session";
export const LOGIN_COOKIE = "ops_login";

export type Session = { at: string; rt?: string; exp: number };
export type Identity = { username: string; roles: string[]; tenantId: string | null };

let keyPromise: Promise<Uint8Array> | null = null;
function key(): Promise<Uint8Array> {
  keyPromise ??= (async () => {
    const secret = process.env.SESSION_SECRET;
    if (!secret || secret.length < 32) throw new Error("SESSION_SECRET must be at least 32 characters");
    return new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(secret)));
  })();
  return keyPromise;
}

export async function seal(payload: Record<string, unknown>, maxAgeSeconds: number): Promise<string> {
  return new EncryptJWT(payload)
    .setProtectedHeader({ alg: "dir", enc: "A256GCM" })
    .setIssuedAt()
    .setExpirationTime(`${maxAgeSeconds}s`)
    .encrypt(await key());
}

export async function unseal<T>(value: string | undefined): Promise<T | null> {
  if (!value) return null;
  try {
    const { payload } = await jwtDecrypt(value, await key());
    return payload as T;
  } catch {
    return null;
  }
}

const cookieOptions = (maxAge: number) => ({
  httpOnly: true,
  sameSite: "lax" as const,
  secure: (process.env.APP_URL ?? "").startsWith("https://"),
  path: "/",
  maxAge,
});

export async function readSession(): Promise<Session | null> {
  return unseal<Session>((await cookies()).get(SESSION_COOKIE)?.value);
}

export async function writeSession(tokens: { access_token: string; refresh_token?: string; expires_in?: number }) {
  const session: Session = {
    at: tokens.access_token,
    rt: tokens.refresh_token,
    exp: Math.floor(Date.now() / 1000) + (tokens.expires_in ?? 300),
  };
  const jar = await cookies();
  jar.set(SESSION_COOKIE, await seal(session, 36000), cookieOptions(36000));
  return session;
}

export async function clearSession() {
  (await cookies()).delete(SESSION_COOKIE);
}

/** Returns a session with a valid access token, refreshing it when close to expiry. Route handlers only. */
export async function freshSession(): Promise<Session | null> {
  const session = await readSession();
  if (!session) return null;
  if (session.exp - 30 > Date.now() / 1000) return session;
  if (!session.rt) return null;
  try {
    const tokens = await client.refreshTokenGrant(oidcConfig(), session.rt);
    return await writeSession({
      access_token: tokens.access_token,
      refresh_token: tokens.refresh_token ?? session.rt,
      expires_in: tokens.expires_in,
    });
  } catch {
    await clearSession();
    return null;
  }
}

/** Display-only identity decoded from the access token. The API verifies the token on every call. */
export function identityFrom(session: Session | null): Identity | null {
  if (!session) return null;
  try {
    const claims = JSON.parse(Buffer.from(session.at.split(".")[1], "base64url").toString("utf8"));
    const roles: string[] = (claims.realm_access?.roles ?? []).filter((r: string) =>
      ["operator", "supervisor", "admin"].includes(r),
    );
    return { username: claims.preferred_username ?? claims.sub, roles, tenantId: claims.tenant_id ?? null };
  } catch {
    return null;
  }
}

export const hasRole = (identity: Identity | null, minimum: "operator" | "supervisor" | "admin") => {
  const rank = { operator: 1, supervisor: 2, admin: 3 } as const;
  return !!identity?.roles.some((r) => rank[r as keyof typeof rank] >= rank[minimum]);
};
