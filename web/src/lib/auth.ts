const TOKEN_KEY = "redactproof.access_token";

/**
 * Client-side-only token store. Standing in for Cognito's hosted-UI session handling
 * (redirect + httpOnly cookie set server-side) until a Cognito user pool exists — see
 * specs/02-architecture.md ADR-7 and app/auth/dev_provider.py on the API side.
 */
export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  window.localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  window.localStorage.removeItem(TOKEN_KEY);
}
