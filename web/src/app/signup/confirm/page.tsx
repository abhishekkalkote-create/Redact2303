"use client";

import { Suspense, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api, problemMessage } from "@/lib/api-client";

/** POST /v1/auth/confirm-signup — completes the code Cognito emailed from /signup. */
function ConfirmSignupForm() {
  const router = useRouter();
  const params = useSearchParams();
  const [email, setEmail] = useState(params.get("email") ?? "");
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    const { error: apiError } = await api.POST("/v1/auth/confirm-signup", {
      body: { email, code },
    });
    setLoading(false);
    if (apiError) {
      setError(problemMessage(apiError));
      return;
    }
    setDone(true);
    setTimeout(() => router.push("/login"), 1500);
  }

  return (
    <main id="main-content" className="flex flex-1 items-center justify-center p-6">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>Confirm your email</CardTitle>
          <CardDescription>
            {done ? "Account confirmed — redirecting to sign in…" : "Enter the code we emailed you."}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {!done && (
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
                <Label htmlFor="code">Confirmation code</Label>
                <Input id="code" required value={code} onChange={(e) => setCode(e.target.value)} />
              </div>
              {error && <p className="text-sm text-red-600">{error}</p>}
              <Button type="submit" disabled={loading}>
                {loading ? "Confirming…" : "Confirm account"}
              </Button>
              <Link href="/login" className="text-sm text-neutral-500 underline">
                Back to sign in
              </Link>
            </form>
          )}
        </CardContent>
      </Card>
    </main>
  );
}

export default function ConfirmSignupPage() {
  return (
    <Suspense>
      <ConfirmSignupForm />
    </Suspense>
  );
}
