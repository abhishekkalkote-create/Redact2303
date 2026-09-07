"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api, problemMessage } from "@/lib/api-client";
import { setToken } from "@/lib/auth";

/**
 * Real sign-in: POST /v1/auth/login (Cognito USER_PASSWORD_AUTH - see
 * app/auth/cognito.py's password_login() docstring for why this, not Hosted-UI/OAuth).
 *
 * The dev-login stand-in (POST /v1/auth/dev-login, 404s outside env=="local") is kept
 * as a local-only fallback below the real form - gated on NODE_ENV, Next's own
 * build-time signal for "this is a local `next dev` run", not a deployment target.
 */
export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const [showDevLogin, setShowDevLogin] = useState(false);
  const [devName, setDevName] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    const { data, error: apiError } = await api.POST("/v1/auth/login", {
      body: { email, password },
    });
    setLoading(false);
    if (apiError) {
      setError(problemMessage(apiError));
      return;
    }
    if (data) {
      setToken(data.access_token);
      router.push("/");
    }
  }

  async function handleDevLogin(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    const { data, error: apiError } = await api.POST("/v1/auth/dev-login", {
      body: { email, name: devName || "Dev User" },
    });
    setLoading(false);
    if (apiError) {
      setError(problemMessage(apiError));
      return;
    }
    if (data) {
      setToken(data.access_token);
      router.push("/");
    }
  }

  return (
    <main id="main-content" className="flex flex-1 items-center justify-center p-6">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>RedactProof</CardTitle>
          <CardDescription>Sign in to your organization.</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={showDevLogin ? handleDevLogin : handleSubmit} className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@agency.gov"
              />
            </div>
            {showDevLogin ? (
              <div className="flex flex-col gap-2">
                <Label htmlFor="dev-name">Name</Label>
                <Input id="dev-name" value={devName} onChange={(e) => setDevName(e.target.value)} placeholder="Jane Analyst" />
              </div>
            ) : (
              <div className="flex flex-col gap-2">
                <Label htmlFor="password">Password</Label>
                <Input
                  id="password"
                  type="password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
              </div>
            )}
            {error && <p className="text-sm text-red-600">{error}</p>}
            <Button type="submit" disabled={loading}>
              {loading ? "Signing in…" : "Sign in"}
            </Button>
            {!showDevLogin && (
              <>
                <Link href="/login/forgot-password" className="text-sm text-neutral-500 underline">
                  Forgot password?
                </Link>
                <Link href="/signup" className="text-sm text-neutral-500 underline">
                  Don&apos;t have an account? Sign up
                </Link>
              </>
            )}
          </form>
          {process.env.NODE_ENV === "development" && (
            <button
              type="button"
              onClick={() => setShowDevLogin((v) => !v)}
              className="mt-4 text-xs text-neutral-500 underline"
            >
              {showDevLogin ? "Use real sign-in" : "Use dev login (local only)"}
            </button>
          )}
        </CardContent>
      </Card>
    </main>
  );
}
