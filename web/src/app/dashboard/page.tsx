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
import { Tabs, TabsList, TabsPanel, TabsTrigger } from "@/components/ui/tabs";
import { api, problemMessage } from "@/lib/api-client";
import { clearToken, getToken } from "@/lib/auth";

const ROLES = ["reviewer", "supervisor", "agency_admin", "billing_admin"];

const KPI_LABELS: Record<string, string> = {
  new: "New",
  processing: "Processing",
  ready_for_review: "Ready for review",
  in_review: "In review",
  awaiting_approval: "Awaiting approval",
  completed: "Completed",
};

const STATUS_VARIANT: Record<string, "default" | "secondary" | "outline" | "destructive"> = {
  ready_for_review: "default",
  in_review: "default",
  awaiting_approval: "secondary",
  review_complete: "secondary",
  exported: "secondary",
  error: "destructive",
};

type QueueTab = "mine" | "team" | "exports";

function QueueDashboard() {
  const [tab, setTab] = useState<QueueTab>("mine");
  const [lowConfidenceFirst, setLowConfidenceFirst] = useState(false);

  const meQuery = useQuery({
    queryKey: ["me"],
    queryFn: async () => {
      const { data, error } = await api.GET("/v1/orgs/current/members/me", {});
      if (error) throw error;
      return data;
    },
  });
  const isSupervisor = meQuery.data?.role === "supervisor" || meQuery.data?.role === "agency_admin";

  const summaryQuery = useQuery({
    queryKey: ["dashboard-summary"],
    queryFn: async () => {
      const { data, error } = await api.GET("/v1/dashboard/summary", {});
      if (error) throw error;
      return data;
    },
    refetchInterval: 10000,
  });

  const myQueueQuery = useQuery({
    queryKey: ["documents", "mine", lowConfidenceFirst],
    queryFn: async () => {
      const { data, error } = await api.GET("/v1/documents", {
        params: {
          query: {
            assignee: "me",
            ...(lowConfidenceFirst ? { sort: "low_confidence_first" } : {}),
          },
        },
      });
      if (error) throw error;
      return data;
    },
    enabled: tab === "mine",
  });

  const teamQueueQuery = useQuery({
    queryKey: ["dashboard-team-queue"],
    queryFn: async () => {
      const { data, error } = await api.GET("/v1/dashboard/team-queue", {});
      if (error) throw error;
      return data;
    },
    enabled: tab === "team" && isSupervisor,
  });

  const exportsQuery = useQuery({
    queryKey: ["exports"],
    queryFn: async () => {
      const { data, error } = await api.GET("/v1/exports", {});
      if (error) throw error;
      return data;
    },
    enabled: tab === "exports",
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>Queues</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          {Object.entries(KPI_LABELS).map(([key, label]) => (
            <div key={key} className="rounded-lg border p-3">
              <p className="text-xs text-neutral-500">{label}</p>
              <p className="text-2xl font-semibold">
                {summaryQuery.isLoading ? "…" : (summaryQuery.data?.[key as keyof typeof summaryQuery.data] ?? 0)}
              </p>
            </div>
          ))}
        </div>

        <Tabs value={tab} onValueChange={(v) => setTab(v as QueueTab)}>
          <TabsList>
            <TabsTrigger value="mine">My queue</TabsTrigger>
            {isSupervisor && <TabsTrigger value="team">Team queue</TabsTrigger>}
            <TabsTrigger value="exports">Recent exports</TabsTrigger>
          </TabsList>

          <TabsPanel value="mine">
            <div className="flex flex-col gap-3">
              <label className="flex items-center gap-2 text-sm text-neutral-600">
                <input
                  type="checkbox"
                  checked={lowConfidenceFirst}
                  onChange={(e) => setLowConfidenceFirst(e.target.checked)}
                />
                Sort low-confidence-first
              </label>
              {myQueueQuery.isLoading ? (
                <p className="text-sm text-neutral-500">Loading…</p>
              ) : myQueueQuery.data?.length === 0 ? (
                <p className="text-sm text-neutral-500">Nothing assigned to you right now.</p>
              ) : (
                <ul className="flex flex-col divide-y">
                  {myQueueQuery.data?.map((doc) => (
                    <li key={doc.id} className="flex items-center justify-between py-2">
                      <Link href={`/documents/${doc.id}/review`} className="font-medium hover:underline">
                        {doc.filename}
                      </Link>
                      <div className="flex items-center gap-2 text-xs text-neutral-500">
                        {doc.due_date && <span>due {new Date(doc.due_date).toLocaleDateString()}</span>}
                        <Badge variant={STATUS_VARIANT[doc.status] ?? "outline"}>{doc.status}</Badge>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </TabsPanel>

          {isSupervisor && (
            <TabsPanel value="team">
              <div className="flex flex-col gap-2">
                {teamQueueQuery.isLoading ? (
                  <p className="text-sm text-neutral-500">Loading…</p>
                ) : teamQueueQuery.data?.length === 0 ? (
                  <p className="text-sm text-neutral-500">No active reviewers yet.</p>
                ) : (
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b text-left text-neutral-500">
                        <th scope="col" className="py-1 font-medium">Reviewer</th>
                        <th scope="col" className="py-1 font-medium">Assigned</th>
                        <th scope="col" className="py-1 font-medium">Overdue</th>
                        <th scope="col" className="py-1 font-medium">Due soon</th>
                      </tr>
                    </thead>
                    <tbody>
                      {teamQueueQuery.data?.map((row) => (
                        <tr key={row.user_id} className="border-b last:border-0">
                          <td className="py-2">
                            {row.name} <span className="text-neutral-500">({row.email})</span>
                          </td>
                          <td className="py-2">{row.assigned_count}</td>
                          <td className="py-2">
                            {row.overdue_count > 0 ? (
                              <Badge variant="destructive">{row.overdue_count}</Badge>
                            ) : (
                              row.overdue_count
                            )}
                          </td>
                          <td className="py-2">{row.due_soon_count}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            </TabsPanel>
          )}

          <TabsPanel value="exports">
            <div className="flex flex-col gap-2">
              {exportsQuery.isLoading ? (
                <p className="text-sm text-neutral-500">Loading…</p>
              ) : exportsQuery.data?.length === 0 ? (
                <p className="text-sm text-neutral-500">No exports yet.</p>
              ) : (
                <ul className="flex flex-col divide-y">
                  {exportsQuery.data?.map((exp) => (
                    <li key={exp.id} className="flex items-center justify-between py-2 text-sm">
                      <span>
                        {exp.type} <span className="text-neutral-500">({exp.doc_id})</span>
                      </span>
                      <span className="text-xs text-neutral-500">{new Date(exp.created_at).toLocaleString()}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </TabsPanel>
        </Tabs>
      </CardContent>
    </Card>
  );
}

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

  // specs/07-ui-spec.md § 1: "land on Dashboard with an 'Upload your first document'
  // hero + optional sample document to try instantly." Shown only while the org has no
  // documents at all — an unfiltered list is the simplest reliable "has this org done
  // anything yet" signal.
  const documentsQuery = useQuery({
    queryKey: ["documents", "all"],
    queryFn: async () => {
      const { data, error } = await api.GET("/v1/documents", {});
      if (error) throw error;
      return data;
    },
    enabled: orgQuery.isSuccess,
  });
  const isNewOrg = documentsQuery.isSuccess && documentsQuery.data.length === 0;

  const [sampleLoading, setSampleLoading] = useState(false);
  const [sampleError, setSampleError] = useState<string | null>(null);

  async function handleTrySample() {
    setSampleError(null);
    setSampleLoading(true);
    const { data, error } = await api.POST("/v1/documents/sample", {});
    setSampleLoading(false);
    if (error) {
      setSampleError(problemMessage(error));
      return;
    }
    if (data) router.push(`/documents/${data.id}/review`);
  }

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
    return <main id="main-content" role="status" className="p-8 text-sm text-neutral-500">Loading…</main>;
  }
  if (!orgQuery.data) return null;

  const org = orgQuery.data;

  return (
    <main id="main-content" className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-6 p-8">
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
          <Link href="/rules" className={buttonVariants({ variant: "outline" })}>
            Rules & Policies
          </Link>
          <Button variant="outline" onClick={handleLogout}>
            Log out
          </Button>
        </div>
      </div>

      <Separator />

      {isNewOrg && (
        <Card>
          <CardHeader>
            <CardTitle>Getting started</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <p className="text-sm text-neutral-500">
              This card goes away once you&rsquo;ve processed a document. One optional step in the meantime:
            </p>
            <ul className="flex flex-col gap-1.5 text-sm text-neutral-500">
              <li>
                <label className="flex items-center gap-2">
                  <input type="checkbox" checked={(membersQuery.data?.length ?? 0) > 1} disabled /> Invite a
                  teammate (skippable)
                </label>
              </li>
            </ul>
            <div className="flex items-center gap-2">
              <Link href="/documents" className={buttonVariants({ variant: "default" })}>
                Upload your first document
              </Link>
              <Button variant="outline" onClick={handleTrySample} disabled={sampleLoading}>
                {sampleLoading ? "Processing sample…" : "Try a sample document instead"}
              </Button>
            </div>
            {sampleError && <p role="alert" className="text-sm text-red-600">{sampleError}</p>}
            <p className="text-xs text-neutral-500">
              The sample document is a fictional incident report shaped to show a few different exemption
              codes — processing it never counts against your plan&rsquo;s usage.
            </p>
          </CardContent>
        </Card>
      )}

      <QueueDashboard />

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
            {inviteError && <p role="alert" className="text-sm text-red-600">{inviteError}</p>}
            {inviteToken && (
              <p role="status" aria-live="polite" className="rounded bg-neutral-100 p-3 text-sm">
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
