"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { api, problemMessage } from "@/lib/api-client";
import { getToken } from "@/lib/auth";
import type { components } from "@redactproof/shared";

type DraftRule = components["schemas"]["DraftRuleOut"];

function slugify(name: string): string {
  return name.toUpperCase().replace(/[^A-Z0-9]+/g, "-").replace(/(^-|-$)/g, "") || "DRAFT";
}

function AcceptForm({ draft, onDone, onCancel }: { draft: DraftRule; onDone: () => void; onCancel: () => void }) {
  const [ruleKey, setRuleKey] = useState(draft.rule_key ?? slugify(draft.name));
  const [packId, setPackId] = useState("");
  const [versionId, setVersionId] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const packsQuery = useQuery({
    queryKey: ["rule-packs"],
    queryFn: async () => {
      const { data, error } = await api.GET("/v1/rule-packs", {});
      if (error) throw error;
      return data;
    },
  });
  const orgPacks = (packsQuery.data ?? []).filter((p) => p.org_id);

  const versionsQuery = useQuery({
    queryKey: ["rule-pack-versions", packId],
    queryFn: async () => {
      const { data, error } = await api.GET("/v1/rule-packs/{rule_pack_id}/versions", {
        params: { path: { rule_pack_id: packId } },
      });
      if (error) throw error;
      return data;
    },
    enabled: !!packId,
  });

  useEffect(() => {
    if (!versionId && versionsQuery.data && versionsQuery.data.length > 0) {
      const draftVersion = versionsQuery.data.find((v) => v.status === "draft");
      setVersionId((draftVersion ?? versionsQuery.data[0]).id);
    }
  }, [versionsQuery.data, versionId]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!versionId) {
      setError("Choose a target rule pack version.");
      return;
    }
    setError(null);
    setSaving(true);
    const { error } = await api.POST("/v1/draft-rules/{draft_rule_id}:accept", {
      params: { path: { draft_rule_id: draft.id } },
      body: { rule_set_version_id: versionId, rule_key: ruleKey },
    });
    setSaving(false);
    if (error) {
      setError(problemMessage(error));
      return;
    }
    onDone();
  }

  return (
    <form onSubmit={handleSubmit} className="mt-2 flex flex-col gap-2 rounded-lg border bg-neutral-50 p-3 dark:bg-neutral-900">
      <div className="flex gap-2">
        <div className="flex flex-1 flex-col gap-1">
          <Label>Rule key</Label>
          <Input value={ruleKey} onChange={(e) => setRuleKey(e.target.value)} required />
        </div>
        <div className="flex flex-1 flex-col gap-1">
          <Label>Target pack</Label>
          <Select value={packId} onValueChange={(v) => { setPackId(v ?? ""); setVersionId(""); }}>
            <SelectTrigger className="w-full"><SelectValue placeholder="Choose a pack…" /></SelectTrigger>
            <SelectContent>
              {orgPacks.map((p) => <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
        <div className="flex flex-1 flex-col gap-1">
          <Label>Version</Label>
          <Select
            value={versionId}
            onValueChange={(v) => setVersionId(v ?? "")}
            items={Object.fromEntries((versionsQuery.data ?? []).map((v) => [v.id, `v${v.version} — ${v.status}`]))}
          >
            <SelectTrigger className="w-full"><SelectValue placeholder="…" /></SelectTrigger>
            <SelectContent>
              {(versionsQuery.data ?? []).map((v) => (
                <SelectItem key={v.id} value={v.id}>v{v.version} — {v.status}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>
      {error && <p className="text-sm text-red-600">{error}</p>}
      <div className="flex gap-2">
        <Button type="submit" size="sm" disabled={saving || !packId}>{saving ? "Adding…" : "Add to draft version"}</Button>
        <Button type="button" size="sm" variant="outline" onClick={onCancel}>Cancel</Button>
      </div>
    </form>
  );
}

function RejectForm({ draft, onDone, onCancel }: { draft: DraftRule; onDone: () => void; onCancel: () => void }) {
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSaving(true);
    const { error } = await api.POST("/v1/draft-rules/{draft_rule_id}:reject", {
      params: { path: { draft_rule_id: draft.id } },
      body: { note: note || null },
    });
    setSaving(false);
    if (error) {
      setError(problemMessage(error));
      return;
    }
    onDone();
  }

  return (
    <form onSubmit={handleSubmit} className="mt-2 flex flex-col gap-2 rounded-lg border bg-neutral-50 p-3 dark:bg-neutral-900">
      <Textarea placeholder="Reason (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
      {error && <p className="text-sm text-red-600">{error}</p>}
      <div className="flex gap-2">
        <Button type="submit" size="sm" variant="destructive" disabled={saving}>{saving ? "Rejecting…" : "Confirm reject"}</Button>
        <Button type="button" size="sm" variant="outline" onClick={onCancel}>Cancel</Button>
      </div>
    </form>
  );
}

function DraftRuleCard({ draft, onChanged }: { draft: DraftRule; onChanged: () => void }) {
  const [action, setAction] = useState<"accept" | "reject" | null>(null);

  return (
    <div className="rounded-lg border p-3">
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="flex items-center gap-2">
            <span className="font-medium">{draft.name}</span>
            <Badge variant="outline">{draft.trigger_type}</Badge>
            <Badge variant={draft.status === "pending" ? "default" : draft.status === "accepted" ? "secondary" : "outline"}>
              {draft.status}
            </Badge>
          </div>
          {draft.source_ref && (
            <p className="mt-1 text-xs text-neutral-500" title={draft.source_ref}>
              Source: {draft.source_ref.length > 140 ? `${draft.source_ref.slice(0, 140)}…` : draft.source_ref}
            </p>
          )}
          {draft.ai_notes && <p className="mt-1 text-xs text-amber-700">AI note: {draft.ai_notes}</p>}
        </div>
        {draft.status === "pending" && (
          <div className="flex shrink-0 gap-1">
            <Button size="xs" onClick={() => setAction(action === "accept" ? null : "accept")}>Accept</Button>
            <Button size="xs" variant="outline" onClick={() => setAction(action === "reject" ? null : "reject")}>Reject</Button>
          </div>
        )}
      </div>
      <pre className="mt-2 overflow-x-auto rounded bg-neutral-100 p-2 text-xs dark:bg-neutral-900">
        {JSON.stringify(draft.config, null, 2)}
      </pre>
      {action === "accept" && (
        <AcceptForm draft={draft} onDone={() => { setAction(null); onChanged(); }} onCancel={() => setAction(null)} />
      )}
      {action === "reject" && (
        <RejectForm draft={draft} onDone={() => { setAction(null); onChanged(); }} onCancel={() => setAction(null)} />
      )}
    </div>
  );
}

export default function ManualDraftRulesPage() {
  const router = useRouter();
  const params = useParams<{ manualId: string }>();
  const manualId = params.manualId;
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!getToken()) router.replace("/login");
  }, [router]);

  const manualsQuery = useQuery({
    queryKey: ["manuals"],
    queryFn: async () => {
      const { data, error } = await api.GET("/v1/manuals", {});
      if (error) throw error;
      return data;
    },
  });
  const manual = manualsQuery.data?.find((m) => m.id === manualId);

  const draftsQuery = useQuery({
    queryKey: ["draft-rules", manualId],
    queryFn: async () => {
      const { data, error } = await api.GET("/v1/manuals/{manual_id}/draft-rules", {
        params: { path: { manual_id: manualId } },
      });
      if (error) throw error;
      return data;
    },
  });

  function refetch() {
    queryClient.invalidateQueries({ queryKey: ["draft-rules", manualId] });
  }

  const pending = (draftsQuery.data ?? []).filter((d) => d.status === "pending");
  const decided = (draftsQuery.data ?? []).filter((d) => d.status !== "pending");

  return (
    <main className="mx-auto flex w-full max-w-4xl flex-1 flex-col gap-6 p-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">{manual?.filename ?? "Manual"}</h1>
          {manual && <Badge variant="outline">{manual.extraction_status}</Badge>}
        </div>
        <Link href="/rules" className="text-sm text-neutral-500 hover:underline">← Rules & Policies</Link>
      </div>

      {draftsQuery.isLoading ? (
        <p className="text-sm text-neutral-500">Loading…</p>
      ) : (draftsQuery.data ?? []).length === 0 ? (
        <p className="text-sm text-neutral-500">
          No draft rules extracted from this manual{manual?.extraction_status === "failed" ? " (extraction failed)" : "."}
        </p>
      ) : (
        <>
          <div>
            <p className="mb-2 text-sm font-medium">Pending review ({pending.length})</p>
            <div className="flex flex-col gap-3">
              {pending.map((d) => <DraftRuleCard key={d.id} draft={d} onChanged={refetch} />)}
            </div>
          </div>
          {decided.length > 0 && (
            <div>
              <p className="mb-2 text-sm font-medium text-neutral-500">Already decided ({decided.length})</p>
              <div className="flex flex-col gap-3">
                {decided.map((d) => <DraftRuleCard key={d.id} draft={d} onChanged={refetch} />)}
              </div>
            </div>
          )}
        </>
      )}
    </main>
  );
}
