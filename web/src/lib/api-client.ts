import createClient from "openapi-fetch";
import type { paths } from "@redactproof/shared";
import { clearToken, getToken } from "./auth";

const baseUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export const api = createClient<paths>({ baseUrl });

// Real Cognito access/ID tokens expire in ~1 hour, and this app has no refresh-token flow
// yet - localStorage still holds a now-invalid token indefinitely after that. Without
// this, every authenticated query on every page just fails silently (or, on the
// dashboard, got misread as "this user has no org yet" and bounced to onboarding - a real
// bug found from an actual expired-session report, not a hypothetical). These are the
// only routes that legitimately expect a 401 for a reason OTHER than "your session
// expired" (bad credentials/codes) - never bounce those to /login mid-attempt.
const AUTH_PATHS_WHERE_401_IS_EXPECTED = [
  "/v1/auth/login",
  "/v1/auth/signup",
  "/v1/auth/confirm-signup",
  "/v1/auth/forgot-password",
  "/v1/auth/reset-password",
  "/v1/auth/dev-login",
];

api.use({
  onRequest({ request }) {
    const token = getToken();
    if (token) request.headers.set("Authorization", `Bearer ${token}`);
    return request;
  },
  onResponse({ request, response }) {
    if (response.status === 401 && typeof window !== "undefined") {
      const path = new URL(request.url).pathname;
      const expected = AUTH_PATHS_WHERE_401_IS_EXPECTED.some((p) => path.endsWith(p));
      if (!expected && window.location.pathname !== "/login") {
        clearToken();
        window.location.href = "/login";
      }
    }
    return response;
  },
});

/** RFC 9457 problem+json body (see specs/04-api-spec.md § Conventions and api/app/core/errors.py). */
export interface ProblemDetail {
  type: string;
  title: string;
  status: number;
  detail?: string;
  instance?: string;
  errors?: Array<{ loc: (string | number)[]; msg: string }>;
}

export function problemMessage(error: unknown): string {
  const problem = error as Partial<ProblemDetail> | undefined;
  return problem?.detail ?? problem?.title ?? "Something went wrong.";
}
