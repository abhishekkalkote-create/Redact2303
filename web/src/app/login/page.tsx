"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api, problemMessage } from "@/lib/api-client";
import { setToken } from "@/lib/auth";

/**
 * Stands in for Cognito's hosted-UI login/signup flow until a user pool exists
 * (specs/02-architecture.md ADR-7) — hits POST /v1/auth/dev-login, which the API only
 * enables when ENV=local. Real signup (POST /v1/auth/signup) 501s until then.
 */
export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    const { data, error: apiError } = await api.POST("/v1/auth/dev-login", {
      body: { email, name: name || "Dev User" },
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
          <CardDescription>
            Dev login — stands in for Cognito hosted UI until a user pool is set up.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
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
            <div className="flex flex-col gap-2">
              <Label htmlFor="name">Name</Label>
              <Input id="name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Jane Analyst" />
            </div>
            {error && <p className="text-sm text-red-600">{error}</p>}
            <Button type="submit" disabled={loading}>
              {loading ? "Signing in…" : "Continue"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </main>
  );
}
