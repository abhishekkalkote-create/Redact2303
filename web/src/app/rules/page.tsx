"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { api, problemMessage } from "@/lib/api-client";
import { getToken } from "@/lib/auth";

type Section = "packs" | "taxonomy" | "manuals" | "improvements";

const CATEGORIES = ["core_pii", "public_safety", "hr", "legal", "health", "custom"];

const MANUAL_STATUS_VARIANT: Record<string, "default" | "secondary" | "outline" | "destructive"> = {
  completed: "secondary",
  processing: "default",
  pending: "outline",
  failed: "destructive",
};

function RulePacksSection() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [name, setName] = useState("");
  const [category, setCategory] = useState("custom");
  const [cloneFromPackId, setCloneFromPackId] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const packsQuery = useQuery({
    queryKey: ["rule-packs"],
    queryFn: async () => {
      const { data, error } = await api.GET("/v1/rule-packs", {});
      if (error) throw error;
      return data;
    },
  });

  const starterPacks = (packsQuery.data ?? []).filter((p) => !p.org_id);
  const orgPacks = (packsQuery.data ?? []).filter((p) => p.org_id);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setCreateError(null);
    setCreating(true);
    const { data, error } = await api.POST("/v1/rule-packs", {
      body: { name, category, clone_from_pack_id: cloneFromPackId || null },
    });
    setCreating(false);
    if (error) {
      setCreateError(problemMessage(error));
      return;
    }
    queryClient.invalidateQueries({ queryKey: ["rule-packs"] });
    if (data?.id) router.push(`/rules/${data.id}`);
  }

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader className="flex items-center justify-between">
          <CardTitle>Starter packs</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="mb-3 text-xs text-neutral-500">
            Global packs maintained by RedactProof. Clone one to customize it for your org.
          </p>
          {packsQuery.isLoading ? (
            <p className="text-sm text-neutral-500">Loading…</p>
          ) : (
            <ul className="flex flex-col divide-y">
              {starterPacks.map((pack) => (
                <li key={pack.id} className="flex items-center justify-between py-2">
                  <div>
                    <Link href={`/rules/${pack.id}`} className="font-medium hover:underline">
                      {pack.name}
                    </Link>
                    <p className="text-xs text-neutral-500">{pack.description}</p>
                  </div>
                  <Badge variant="outline">{pack.category}</Badge>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex items-center justify-between">
          <CardTitle>Org rule packs</CardTitle>
          <Button size="sm" onClick={() => setShowCreate((v) => !v)}>
            {showCreate ? "Cancel" : "+ New pack"}
          </Button>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {showCreate && (
            <form onSubmit={handleCreate} className="flex flex-col gap-3 rounded-lg border p-3">
              <div className="flex gap-3">
                <div className="flex flex-1 flex-col gap-1.5">
                  <Label htmlFor="packName">Name</Label>
                  <Input id="packName" required value={name} onChange={(e) => setName(e.target.value)} />
                </div>
                <div className="flex w-40 flex-col gap-1.5">
                  <Label>Category</Label>
                  <Select value={category} onValueChange={(v) => v && setCategory(v)}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {CATEGORIES.map((c) => (
                        <SelectItem key={c} value={c}>{c}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>
              <div className="flex flex-col gap-1.5">
                <Label>Clone rules from (optional)</Label>
                <Select value={cloneFromPackId} onValueChange={(v) => setCloneFromPackId(v ?? "")}>
                  <SelectTrigger className="w-full"><SelectValue placeholder="Start empty" /></SelectTrigger>
                  <SelectContent>
                    {(packsQuery.data ?? []).map((p) => (
                      <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              {createError && <p className="text-sm text-red-600">{createError}</p>}
              <Button type="submit" disabled={creating} className="self-start">
                {creating ? "Creating…" : "Create pack"}
              </Button>
            </form>
          )}
          {packsQuery.isLoading ? (
            <p className="text-sm text-neutral-500">Loading…</p>
          ) : orgPacks.length === 0 ? (
            <p className="text-sm text-neutral-500">No org packs yet — clone a starter pack or create a custom one.</p>
          ) : (
            <ul className="flex flex-col divide-y">
              {orgPacks.map((pack) => (
                <li key={pack.id} className="flex items-center justify-between py-2">
                  <div>
                    <Link href={`/rules/${pack.id}`} className="font-medium hover:underline">
                      {pack.name}
                    </Link>
                    {pack.cloned_from_pack_id && (
                      <p className="text-xs text-neutral-500">cloned from a starter pack</p>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    <Badge variant="outline">{pack.category}</Badge>
                    <Badge variant={pack.status === "active" ? "secondary" : "outline"}>{pack.status}</Badge>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function TaxonomySection() {
  const codesQuery = useQuery({
    queryKey: ["exemption-codes"],
    queryFn: async () => {
      const { data, error } = await api.GET("/v1/exemption-codes", {});
      if (error) throw error;
      return data;
    },
  });

  const codes = codesQuery.data ?? [];
  const federal = codes.filter((c) => c.level === "federal");
  const byState = new Map<string, typeof codes>();
  for (const c of codes) {
    if (c.level === "state" && c.state) {
      byState.set(c.state, [...(byState.get(c.state) ?? []), c]);
    }
  }
  const orgOnly = codes.filter((c) => !c.library_id);

  function Group({ title, items }: { title: string; items: typeof codes }) {
    if (items.length === 0) return null;
    return (
      <div>
        <p className="mb-1 text-xs font-medium text-neutral-500">{title}</p>
        <ul className="flex flex-col divide-y rounded-lg border">
          {items.map((code) => (
            <li key={code.id} className="flex items-center justify-between px-3 py-2 text-sm">
              <div>
                <span className="font-mono font-medium">{code.code}</span>{" "}
                <span className="text-neutral-500">— {code.label}</span>
                {code.statute_citation && (
                  <p className="text-xs text-neutral-500">{code.statute_citation}</p>
                )}
              </div>
              <Badge variant="outline">{code.status}</Badge>
            </li>
          ))}
        </ul>
      </div>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Exemption taxonomy</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {codesQuery.isLoading ? (
          <p className="text-sm text-neutral-500">Loading…</p>
        ) : (
          <>
            <Group title="Federal" items={federal} />
            {[...byState.entries()].map(([state, items]) => (
              <Group key={state} title={`State — ${state}`} items={items} />
            ))}
            <Group title="Org-defined reason codes" items={orgOnly} />
          </>
        )}
      </CardContent>
    </Card>
  );
}

function ManualsSection() {
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);

  const manualsQuery = useQuery({
    queryKey: ["manuals"],
    queryFn: async () => {
      const { data, error } = await api.GET("/v1/manuals", {});
      if (error) throw error;
      return data;
    },
  });

  async function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    setUploadError(null);
    const { error } = await api.POST("/v1/manuals", {
      // @ts-expect-error - openapi-fetch's multipart/form-data typing wants FormData directly as body
      body: (() => {
        const form = new FormData();
        form.append("file", file);
        return form;
      })(),
    });
    setUploading(false);
    if (error) {
      setUploadError(problemMessage(error));
      return;
    }
    queryClient.invalidateQueries({ queryKey: ["manuals"] });
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  return (
    <Card>
      <CardHeader className="flex items-center justify-between">
        <CardTitle>Manuals</CardTitle>
        <div>
          <input
            ref={fileInputRef}
            type="file"
            accept="application/pdf"
            className="hidden"
            onChange={handleFileChange}
          />
          <Button size="sm" onClick={() => fileInputRef.current?.click()} disabled={uploading}>
            {uploading ? "Uploading…" : "Upload manual (PDF)"}
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        <p className="mb-3 text-xs text-neutral-500">
          Upload an exemption guide or SOP — RedactProof extracts candidate rules per page for you to accept, edit, or reject.
        </p>
        {uploadError && <p className="mb-2 text-sm text-red-600">{uploadError}</p>}
        {manualsQuery.isLoading ? (
          <p className="text-sm text-neutral-500">Loading…</p>
        ) : manualsQuery.data?.length === 0 ? (
          <p className="text-sm text-neutral-500">No manuals uploaded yet.</p>
        ) : (
          <ul className="flex flex-col divide-y">
            {manualsQuery.data?.map((manual) => (
              <li key={manual.id} className="flex items-center justify-between py-2">
                <div>
                  <Link href={`/rules/manuals/${manual.id}`} className="font-medium hover:underline">
                    {manual.filename}
                  </Link>
                  <p className="text-xs text-neutral-500">
                    uploaded {new Date(manual.created_at).toLocaleString()}
                  </p>
                  {manual.error && <p className="text-xs text-red-600">{manual.error}</p>}
                </div>
                <Badge variant={MANUAL_STATUS_VARIANT[manual.extraction_status] ?? "outline"}>
                  {manual.extraction_status}
                </Badge>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function RuleImprovementsSection() {
  const reportQuery = useQuery({
    queryKey: ["rule-improvements-report"],
    queryFn: async () => {
      const { data, error } = await api.GET("/v1/rule-improvements-report", {});
      if (error) throw error;
      return data;
    },
  });

  if (reportQuery.isLoading) {
    return <p className="text-sm text-neutral-500">Loading…</p>;
  }

  const report = reportQuery.data;
  const rejected = report?.rejected_by_rule ?? [];
  const clusters = report?.manual_clusters ?? [];

  return (
    <div className="flex flex-col gap-6">
      <p className="text-xs text-neutral-500">
        Feedback signal from reviewer decisions — report only, nothing here changes a rule automatically.
        {report && ` Generated ${new Date(report.generated_at).toLocaleString()}.`}
      </p>

      <Card>
        <CardHeader><CardTitle>Rules with high rejection rates</CardTitle></CardHeader>
        <CardContent>
          {rejected.length === 0 ? (
            <p className="text-sm text-neutral-500">No AI candidates have been rejected yet.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-neutral-500">
                    <th className="py-1.5 pr-2 font-medium">Rule</th>
                    <th className="py-1.5 pr-2 font-medium">Rejected</th>
                    <th className="py-1.5 pr-2 font-medium">Total suggested</th>
                    <th className="py-1.5 font-medium">Rejection rate</th>
                  </tr>
                </thead>
                <tbody>
                  {rejected.map((r) => (
                    <tr key={r.rule_key} className="border-b last:border-0">
                      <td className="py-2 pr-2">
                        <span className="font-mono">{r.rule_key}</span>
                        {r.rule_name && <span className="text-neutral-500"> — {r.rule_name}</span>}
                      </td>
                      <td className="py-2 pr-2">{r.rejected_count}</td>
                      <td className="py-2 pr-2">{r.total_count}</td>
                      <td className="py-2">
                        <Badge variant={r.rejection_rate >= 0.5 ? "destructive" : "outline"}>
                          {Math.round(r.rejection_rate * 100)}%
                        </Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Manual redactions no rule caught</CardTitle></CardHeader>
        <CardContent>
          <p className="mb-3 text-xs text-neutral-500">
            Reviewer-added redactions clustered by text shape — a recurring cluster is a candidate for a new rule.
          </p>
          {clusters.length === 0 ? (
            <p className="text-sm text-neutral-500">No recurring manual-redaction patterns yet.</p>
          ) : (
            <ul className="flex flex-col divide-y rounded-lg border">
              {clusters.map((c) => (
                <li key={c.pattern} className="flex flex-col gap-1 px-3 py-2 text-sm">
                  <div className="flex items-center justify-between">
                    <span className="font-mono">{c.pattern}</span>
                    <Badge variant="secondary">{c.count} occurrences</Badge>
                  </div>
                  {c.exemption_codes.length > 0 && (
                    <p className="text-xs text-neutral-500">codes used: {c.exemption_codes.join(", ")}</p>
                  )}
                  <p className="truncate text-xs text-neutral-500">e.g. {c.sample_texts.join(" · ")}</p>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

export default function RulesPage() {
  const router = useRouter();
  const [section, setSection] = useState<Section>("packs");

  useEffect(() => {
    if (!getToken()) router.replace("/login");
  }, [router]);

  return (
    <main className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-6 p-8">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Rules & Policies</h1>
        <Link href="/documents" className="text-sm text-neutral-500 hover:underline">
          ← Documents
        </Link>
      </div>

      <div className="flex items-center gap-2 border-b pb-2">
        <Button variant={section === "packs" ? "default" : "outline"} size="sm" onClick={() => setSection("packs")}>
          Rule packs
        </Button>
        <Button variant={section === "taxonomy" ? "default" : "outline"} size="sm" onClick={() => setSection("taxonomy")}>
          Exemption taxonomy
        </Button>
        <Button variant={section === "manuals" ? "default" : "outline"} size="sm" onClick={() => setSection("manuals")}>
          Manuals
        </Button>
        <Button variant={section === "improvements" ? "default" : "outline"} size="sm" onClick={() => setSection("improvements")}>
          Suggested improvements
        </Button>
      </div>

      {section === "packs" && <RulePacksSection />}
      {section === "taxonomy" && <TaxonomySection />}
      {section === "manuals" && <ManualsSection />}
      {section === "improvements" && <RuleImprovementsSection />}
    </main>
  );
}
