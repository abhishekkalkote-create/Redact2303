"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api, problemMessage } from "@/lib/api-client";
import { getToken, setToken } from "@/lib/auth";

/** specs/04-api-spec.md POST /invites/{token}/accept — the invitee logs in (dev-login for
 * now), then this page calls accept on their behalf. */
export default function AcceptInvitePage() {
  const router = useRouter();
  const params = useParams<{ token: string }>();
  const [loggedIn, setLoggedIn] = useState(false);
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setLoggedIn(!!getToken());
  }, []);

  async function handleLoginThenAccept(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    const { data, error: loginError } = await api.POST("/v1/auth/dev-login", {
      body: { email, name: name || "Dev User" },
    });
    if (loginError) {
      setLoading(false);
      setError(problemMessage(loginError));
      return;
    }
    setToken(data.access_token);
    await accept();
  }

  async function accept() {
    setError(null);
    setLoading(true);
    const { error: acceptError } = await api.POST("/v1/invites/{token}/accept", {
      params: { path: { token: params.token } },
    });
    setLoading(false);
    if (acceptError) {
      setError(problemMessage(acceptError));
      return;
    }
    router.push("/dashboard");
  }

  return (
    <main className="flex flex-1 items-center justify-center p-6">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>Accept invitation</CardTitle>
          <CardDescription>
            {loggedIn
              ? "You're signed in — accept this invite to join the organization."
              : "Sign in with the email this invite was sent to."}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {loggedIn ? (
            <div className="flex flex-col gap-4">
              {error && <p className="text-sm text-red-600">{error}</p>}
              <Button onClick={accept} disabled={loading}>
                {loading ? "Accepting…" : "Accept invite"}
              </Button>
            </div>
          ) : (
            <form onSubmit={handleLoginThenAccept} className="flex flex-col gap-4">
              <div className="flex flex-col gap-2">
                <Label htmlFor="email">Email</Label>
                <Input
                  id="email"
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                />
              </div>
              <div className="flex flex-col gap-2">
                <Label htmlFor="name">Name</Label>
                <Input id="name" value={name} onChange={(e) => setName(e.target.value)} />
              </div>
              {error && <p className="text-sm text-red-600">{error}</p>}
              <Button type="submit" disabled={loading}>
                {loading ? "Working…" : "Sign in & accept"}
              </Button>
            </form>
          )}
        </CardContent>
      </Card>
    </main>
  );
}
