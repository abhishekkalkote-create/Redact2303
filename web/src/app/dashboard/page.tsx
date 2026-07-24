"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { api, problemMessage } from "@/lib/api-client";
import { clearToken, getToken } from "@/lib/auth";

const ROLES = ["reviewer", "supervisor", "agency_admin", "billing_admin"];

export default function DashboardPage() {
  const router = useRouter();
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!getToken()) router.replace("/login");
  }, [router]);

  const orgQuery = useQuery({
    queryKey: ["org"],
    queryFn: async () => {
      const { data, error } = await api.GET("/v1/orgs/current", {});
      if (error) throw error;
      return data;
    },
    retry: false,
  });

  const membersQuery = useQuery({
    queryKey: ["members"],
    queryFn: async () => {
      const { data, error } = await api.GET("/v1/orgs/current/members", {});
      if (error) throw error;
      return data;
    },
    enabled: orgQuery.isSuccess,
  });

  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState("reviewer");
  const [inviteToken, setInviteToken] = useState<string | null>(null);
  const [inviteError, setInviteError] = useState<string | null>(null);
  const [inviting, setInviting] = useState(false);

  useEffect(() => {
    if (orgQuery.isError) router.replace("/onboarding");
  }, [orgQuery.isError, router]);

  async function handleInvite(e: React.FormEvent) {
    e.preventDefault();
    setInviteError(null);
    setInviteToken(null);
    setInviting(true);
    const { data, error } = await api.POST("/v1/orgs/current/invites", {
      body: { email: inviteEmail, role: inviteRole },
    });
    setInviting(false);
    if (error) {
      setInviteError(problemMessage(error));
      return;
    }
    if (data?.token) {
      setInviteToken(data.token);
      setInviteEmail("");
      queryClient.invalidateQueries({ queryKey: ["members"] });
    }
  }

  function handleLogout() {
    clearToken();
    router.push("/login");
  }

  if (orgQuery.isLoading) {
    return <main className="p-8 text-sm text-neutral-500">Loading…</main>;
  }
  if (!orgQuery.data) return null;

  const org = orgQuery.data;

  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-6 p-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">{org.name}</h1>
          <p className="text-sm text-neutral-500">
            {org.jurisdiction_state} · {org.org_type} ·{" "}
            <Badge variant="secondary">{org.plan}</Badge>
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Link href="/documents" className={buttonVariants({ variant: "outline" })}>
            Documents
          </Link>
          <Button variant="outline" onClick={handleLogout}>
            Log out
          </Button>
        </div>
      </div>

      <Separator />

      <Card>
        <CardHeader>
          <CardTitle>Members</CardTitle>
        </CardHeader>
        <CardContent>
          <ul className="flex flex-col gap-2">
            {membersQuery.data?.map((m) => (
              <li key={m.id} className="flex items-center justify-between text-sm">
                <span>
                  {m.name} <span className="text-neutral-500">({m.email})</span>
                </span>
                <Badge variant="outline">{m.role}</Badge>
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Invite a teammate</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleInvite} className="flex flex-col gap-4">
            <div className="flex gap-4">
              <div className="flex flex-1 flex-col gap-2">
                <Label htmlFor="inviteEmail">Email</Label>
                <Input
                  id="inviteEmail"
                  type="email"
                  required
                  value={inviteEmail}
                  onChange={(e) => setInviteEmail(e.target.value)}
                  placeholder="teammate@agency.gov"
                />
              </div>
              <div className="flex w-44 flex-col gap-2">
                <Label htmlFor="inviteRole">Role</Label>
                <Select value={inviteRole} onValueChange={(v) => v && setInviteRole(v)}>
                  <SelectTrigger id="inviteRole">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {ROLES.map((r) => (
                      <SelectItem key={r} value={r}>
                        {r}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
            {inviteError && <p className="text-sm text-red-600">{inviteError}</p>}
            {inviteToken && (
              <p className="rounded bg-neutral-100 p-3 text-sm">
                No email delivery yet (Phase 3) — share this accept link manually:
                <br />
                <code className="break-all">
                  {typeof window !== "undefined" ? window.location.origin : ""}/invites/{inviteToken}/accept
                </code>
              </p>
            )}
            <Button type="submit" disabled={inviting} className="self-start">
              {inviting ? "Sending…" : "Send invite"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </main>
  );
}
