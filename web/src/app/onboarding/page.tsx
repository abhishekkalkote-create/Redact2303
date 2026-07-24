"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { api, problemMessage } from "@/lib/api-client";
import { getToken } from "@/lib/auth";

const ORG_TYPES = [
  { value: "police", label: "Police / Sheriff" },
  { value: "city_clerk", label: "City Clerk" },
  { value: "county", label: "County" },
  { value: "state", label: "State Agency" },
  { value: "school", label: "School District" },
  { value: "other", label: "Other" },
];

const STATES = ["FED", "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "WA", "TX", "NY"];

/** specs/07-ui-spec.md § 1 — "Create your organization" onboarding step. */
export default function OnboardingPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [jurisdictionState, setJurisdictionState] = useState("WA");
  const [orgType, setOrgType] = useState("city_clerk");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!getToken()) router.replace("/login");
  }, [router]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    const { error: apiError } = await api.POST("/v1/orgs", {
      body: { name, jurisdiction_state: jurisdictionState, org_type: orgType },
    });
    setLoading(false);
    if (apiError) {
      setError(problemMessage(apiError));
      return;
    }
    router.push("/dashboard");
  }

  return (
    <main className="flex flex-1 items-center justify-center p-6">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>Create your organization</CardTitle>
          <CardDescription>You&apos;ll be the agency admin.</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
              <Label htmlFor="name">Organization name</Label>
              <Input
                id="name"
                required
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Springfield City Clerk's Office"
              />
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="jurisdiction">Jurisdiction / state</Label>
              <Select value={jurisdictionState} onValueChange={(v) => v && setJurisdictionState(v)}>
                <SelectTrigger id="jurisdiction">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {STATES.map((s) => (
                    <SelectItem key={s} value={s}>
                      {s}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="orgType">Organization type</Label>
              <Select value={orgType} onValueChange={(v) => v && setOrgType(v)}>
                <SelectTrigger id="orgType">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {ORG_TYPES.map((t) => (
                    <SelectItem key={t.value} value={t.value}>
                      {t.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            {error && <p className="text-sm text-red-600">{error}</p>}
            <Button type="submit" disabled={loading}>
              {loading ? "Creating…" : "Create organization"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </main>
  );
}
