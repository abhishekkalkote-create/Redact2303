"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api, problemMessage } from "@/lib/api-client";

/**
 * Real self-serve registration: POST /v1/auth/signup (Cognito sign_up - see
 * app/auth/cognito.py's sign_up() docstring). The account starts unconfirmed and a
 * code is emailed automatically; this redirects to /signup/confirm to complete it.
 */
export default function SignupPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    const { data, error: apiError } = await api.POST("/v1/auth/signup", {
      body: { email, name, password },
    });
    setLoading(false);
    if (apiError) {
      setError(problemMessage(apiError));
      return;
    }
    if (data?.verification_required) {
      router.push(`/signup/confirm?email=${encodeURIComponent(email)}`);
    } else {
      router.push("/login");
    }
  }

  return (
    <main id="main-content" className="flex flex-1 items-center justify-center p-6">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>Create your account</CardTitle>
          <CardDescription>Start redacting documents for your agency.</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
              <Label htmlFor="name">Name</Label>
              <Input
                id="name"
                required
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Jane Analyst"
              />
            </div>
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
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                required
                minLength={12}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>
            {error && <p className="text-sm text-red-600">{error}</p>}
            <Button type="submit" disabled={loading}>
              {loading ? "Creating account…" : "Create account"}
            </Button>
            <Link href="/login" className="text-sm text-neutral-500 underline">
              Already have an account? Sign in
            </Link>
          </form>
        </CardContent>
      </Card>
    </main>
  );
}
