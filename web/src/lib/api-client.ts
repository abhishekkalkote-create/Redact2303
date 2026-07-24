import createClient from "openapi-fetch";
import type { paths } from "@redactproof/shared";
import { getToken } from "./auth";

const baseUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export const api = createClient<paths>({ baseUrl });

api.use({
  onRequest({ request }) {
    const token = getToken();
    if (token) request.headers.set("Authorization", `Bearer ${token}`);
    return request;
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
