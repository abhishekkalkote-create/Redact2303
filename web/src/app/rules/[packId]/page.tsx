"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsList, TabsPanel, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { api, problemMessage } from "@/lib/api-client";
import { getToken } from "@/lib/auth";
import type { components } from "@redactproof/shared";

type Rule = components["schemas"]["RuleOut"];
type Tab = "rules" | "test-bench" | "versions";

const TRIGGER_TYPES = ["regex", "dictionary", "entity", "metadata", "llm_context"];
const CONFIDENCE_POLICIES = ["auto_high", "suggest", "flag_low"];
const SCOPES = ["org", "document_type", "request"];

function splitList(s: string): string[] {
  return s.split(/[,\n]/).map((x) => x.trim()).filter(Boolean);
}

interface RuleFormState {
  rule_key: string;
  name: string;
  trigger_type: string;
  exemption_code_id: string;
  priority: number;
  confidence_policy: string;
  scope: string;
  source_ref: string;
  exclusionsJson: string;
  pattern: string;
  validatorsLuhn: boolean;
  validatorsSsnFormat: boolean;
  contextWords: string;
  contextWindow: number;
  termsText: string;
  entityType: string;
  metadataField: string;
  instruction: string;
}

function ruleToFormState(rule: Rule | null): RuleFormState {
  const config = rule?.config ?? {};
  return {
    rule_key: rule?.rule_key ?? "",
    name: rule?.name ?? "",
    trigger_type: rule?.trigger_type ?? "entity",
    exemption_code_id: rule?.exemption_code_id ?? "",
    priority: rule?.priority ?? 100,
    confidence_policy: rule?.confidence_policy ?? "suggest",
    scope: rule?.scope ?? "org",
    source_ref: rule?.source_ref ?? "",
    exclusionsJson: JSON.stringify(rule?.exclusions ?? [], null, 2),
    pattern: (config.pattern as string) ?? "",
    validatorsLuhn: Array.isArray(config.validators) && (config.validators as string[]).includes("luhn"),
    validatorsSsnFormat: Array.isArray(config.validators) && (config.validators as string[]).includes("ssn_format"),
    contextWords: Array.isArray(config.context_words) ? (config.context_words as string[]).join(", ") : "",
    contextWindow: typeof config.context_window === "number" ? config.context_window : 40,
    termsText: Array.isArray(config.terms) ? (config.terms as string[]).join("\n") : "",
    entityType: (config.entity_type as string) ?? "",
    metadataField: (config.field as string) ?? "",
    instruction: (config.instruction as string) ?? "",
  };
}

function buildConfig(f: RuleFormState): Record<string, unknown> {
  switch (f.trigger_type) {
    case "regex": {
      const validators = [...(f.validatorsLuhn ? ["luhn"] : []), ...(f.validatorsSsnFormat ? ["ssn_format"] : [])];
      return {
        pattern: f.pattern,
        ...(validators.length ? { validators } : {}),
        ...(f.contextWords ? { context_words: splitList(f.contextWords), context_window: f.contextWindow } : {}),
      };
    }
    case "dictionary":
      return { terms: splitList(f.termsText) };
    case "entity":
      return {
        entity_type: f.entityType,
        ...(f.contextWords ? { context_words: splitList(f.contextWords), context_window: f.contextWindow } : {}),
      };
    case "metadata":
      return { field: f.metadataField, pattern: f.pattern };
    case "llm_context":
      return { instruction: f.instruction };
    default:
      return {};
  }
}

function RuleEditorForm({
  initial,
  versionId,
  onDone,
  onCancel,
}: {
  initial: Rule | null;
  versionId: string;
  onDone: () => void;
  onCancel: () => void;
}) {
  const [f, setF] = useState<RuleFormState>(ruleToFormState(initial));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const codesQuery = useQuery({
    queryKey: ["exemption-codes"],
    queryFn: async () => {
      const { data, error } = await api.GET("/v1/exemption-codes", {});
      if (error) throw error;
      return data;
    },
  });

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    let exclusions: unknown[] = [];
    try {
      exclusions = f.exclusionsJson.trim() ? JSON.parse(f.exclusionsJson) : [];
    } catch {
      setError("Exclusions must be valid JSON (an array).");
      return;
    }
    setSaving(true);
    const config = buildConfig(f);
    if (initial) {
      const { error: apiError } = await api.PATCH("/v1/rules/{rule_id}", {
        params: { path: { rule_id: initial.id } },
        body: {
          name: f.name, trigger_type: f.trigger_type, config, exemption_code_id: f.exemption_code_id || null,
          priority: f.priority, confidence_policy: f.confidence_policy, scope: f.scope,
          source_ref: f.source_ref || null, exclusions,
        },
      });
      setSaving(false);
      if (apiError) {
        setError(problemMessage(apiError));
        return;
      }
    } else {
      const { error: apiError } = await api.POST("/v1/rule-set-versions/{version_id}/rules", {
        params: { path: { version_id: versionId } },
        body: {
          rule_key: f.rule_key, name: f.name, trigger_type: f.trigger_type, config,
          exemption_code_id: f.exemption_code_id || null, priority: f.priority,
          confidence_policy: f.confidence_policy, scope: f.scope, source_ref: f.source_ref || null, exclusions,
        },
      });
      setSaving(false);
      if (apiError) {
        setError(problemMessage(apiError));
        return;
      }
    }
    onDone();
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-3 rounded-lg border p-3">
      <div className="flex gap-3">
        {!initial && (
          <div className="flex flex-1 flex-col gap-1.5">
            <Label htmlFor="rule-key">Rule key</Label>
            <Input id="rule-key" required value={f.rule_key} onChange={(e) => setF({ ...f, rule_key: e.target.value })} placeholder="CUSTOM-1" />
          </div>
        )}
        <div className="flex flex-1 flex-col gap-1.5">
          <Label htmlFor="rule-name">Name</Label>
          <Input id="rule-name" required value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
        </div>
        <div className="flex w-44 flex-col gap-1.5">
          <Label htmlFor="rule-trigger-type">Trigger type</Label>
          <Select value={f.trigger_type} onValueChange={(v) => v && setF({ ...f, trigger_type: v })}>
            <SelectTrigger id="rule-trigger-type"><SelectValue /></SelectTrigger>
            <SelectContent>
              {TRIGGER_TYPES.map((t) => <SelectItem key={t} value={t}>{t}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
      </div>

      {(f.trigger_type === "regex" || f.trigger_type === "metadata") && (
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="rule-pattern">Pattern (regex)</Label>
          <Input id="rule-pattern" required value={f.pattern} onChange={(e) => setF({ ...f, pattern: e.target.value })} className="font-mono" />
        </div>
      )}
      {f.trigger_type === "metadata" && (
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="rule-metadata-field">Document metadata field</Label>
          <Input id="rule-metadata-field" required value={f.metadataField} onChange={(e) => setF({ ...f, metadataField: e.target.value })} placeholder="author" />
        </div>
      )}
      {f.trigger_type === "regex" && (
        <div className="flex gap-4">
          <label className="flex items-center gap-2 text-sm">
            <Checkbox checked={f.validatorsLuhn} onCheckedChange={(c) => setF({ ...f, validatorsLuhn: !!c })} />
            Luhn checksum
          </label>
          <label className="flex items-center gap-2 text-sm">
            <Checkbox checked={f.validatorsSsnFormat} onCheckedChange={(c) => setF({ ...f, validatorsSsnFormat: !!c })} />
            SSN format
          </label>
        </div>
      )}
      {f.trigger_type === "entity" && (
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="rule-entity-type">Entity type (Presidio)</Label>
          <Input id="rule-entity-type" required value={f.entityType} onChange={(e) => setF({ ...f, entityType: e.target.value })} placeholder="US_SSN, PERSON, EMAIL_ADDRESS…" />
        </div>
      )}
      {f.trigger_type === "dictionary" && (
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="rule-terms">Terms (one per line)</Label>
          <Textarea id="rule-terms" required value={f.termsText} onChange={(e) => setF({ ...f, termsText: e.target.value })} />
        </div>
      )}
      {(f.trigger_type === "regex" || f.trigger_type === "entity") && (
        <div className="flex gap-3">
          <div className="flex flex-1 flex-col gap-1.5">
            <Label htmlFor="rule-context-words">Context words (comma-separated, optional)</Label>
            <Input id="rule-context-words" value={f.contextWords} onChange={(e) => setF({ ...f, contextWords: e.target.value })} />
          </div>
          <div className="flex w-32 flex-col gap-1.5">
            <Label htmlFor="rule-context-window">Window (chars)</Label>
            <Input id="rule-context-window" type="number" value={f.contextWindow} onChange={(e) => setF({ ...f, contextWindow: Number(e.target.value) })} />
          </div>
        </div>
      )}
      {f.trigger_type === "llm_context" && (
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="rule-instruction">Instruction (natural language — executed by the contextual pass, not the deterministic engine)</Label>
          <Textarea id="rule-instruction" required value={f.instruction} onChange={(e) => setF({ ...f, instruction: e.target.value })} />
        </div>
      )}

      <Separator />

      <div className="flex gap-3">
        <div className="flex flex-1 flex-col gap-1.5">
          <Label htmlFor="rule-exemption-code">Exemption code</Label>
          <Select
            value={f.exemption_code_id}
            onValueChange={(v) => setF({ ...f, exemption_code_id: v ?? "" })}
            items={Object.fromEntries((codesQuery.data ?? []).map((code) => [code.id, `${code.code} — ${code.label}`]))}
          >
            <SelectTrigger id="rule-exemption-code" className="w-full"><SelectValue placeholder="None" /></SelectTrigger>
            <SelectContent>
              {(codesQuery.data ?? []).map((code) => (
                <SelectItem key={code.id} value={code.id}>{code.code} — {code.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex w-32 flex-col gap-1.5">
          <Label htmlFor="rule-priority">Priority</Label>
          <Input id="rule-priority" type="number" value={f.priority} onChange={(e) => setF({ ...f, priority: Number(e.target.value) })} />
        </div>
        <div className="flex w-40 flex-col gap-1.5">
          <Label htmlFor="rule-confidence-policy">Confidence policy</Label>
          <Select value={f.confidence_policy} onValueChange={(v) => v && setF({ ...f, confidence_policy: v })}>
            <SelectTrigger id="rule-confidence-policy"><SelectValue /></SelectTrigger>
            <SelectContent>
              {CONFIDENCE_POLICIES.map((p) => <SelectItem key={p} value={p}>{p}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
        <div className="flex w-36 flex-col gap-1.5">
          <Label htmlFor="rule-scope">Scope</Label>
          <Select value={f.scope} onValueChange={(v) => v && setF({ ...f, scope: v })}>
            <SelectTrigger id="rule-scope"><SelectValue /></SelectTrigger>
            <SelectContent>
              {SCOPES.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="rule-exclusions">Exclusions (JSON array — allowlist / context_not / pattern_carveout)</Label>
        <Textarea id="rule-exclusions" value={f.exclusionsJson} onChange={(e) => setF({ ...f, exclusionsJson: e.target.value })} className="font-mono text-xs" />
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="rule-source-ref">Source reference (optional)</Label>
        <Input id="rule-source-ref" value={f.source_ref} onChange={(e) => setF({ ...f, source_ref: e.target.value })} placeholder="Manual section anchor, NL instruction, …" />
      </div>

      {error && <p className="text-sm text-red-600">{error}</p>}
      <div className="flex gap-2">
        <Button type="submit" disabled={saving}>{saving ? "Saving…" : initial ? "Save changes" : "Create rule"}</Button>
        <Button type="button" variant="outline" onClick={onCancel}>Cancel</Button>
      </div>
      {initial && (
        <p className="text-xs text-neutral-500">
          Editing a published version&rsquo;s rule automatically forks a new draft version — this pack now has (or will get) a draft you can review before publishing.
        </p>
      )}
    </form>
  );
}

function RulesTab({ versionId, onVersionForked }: { versionId: string; onVersionForked: () => void }) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState<Rule | null | "new">(null);
  const [nlInstruction, setNlInstruction] = useState("");
  const [nlLoading, setNlLoading] = useState(false);
  const [nlError, setNlError] = useState<string | null>(null);
  const [nlResult, setNlResult] = useState<components["schemas"]["NlEditResponse"] | null>(null);

  const rulesQuery = useQuery({
    queryKey: ["rules", versionId],
    queryFn: async () => {
      const { data, error } = await api.GET("/v1/rule-set-versions/{version_id}/rules", {
        params: { path: { version_id: versionId } },
      });
      if (error) throw error;
      return data;
    },
  });

  function refetch() {
    queryClient.invalidateQueries({ queryKey: ["rules", versionId] });
    queryClient.invalidateQueries({ queryKey: ["rule-pack-versions"] });
  }

  async function handleDelete(rule: Rule) {
    if (!confirm(`Delete rule ${rule.rule_key}?`)) return;
    const { error } = await api.DELETE("/v1/rules/{rule_id}", { params: { path: { rule_id: rule.id } } });
    if (error) {
      alert(problemMessage(error));
      return;
    }
    refetch();
    onVersionForked();
  }

  async function runNlEdit(e: React.FormEvent) {
    e.preventDefault();
    setNlError(null);
    setNlResult(null);
    setNlLoading(true);
    const { data, error } = await api.POST("/v1/rule-set-versions/{version_id}/nl-edit", {
      params: { path: { version_id: versionId } },
      body: { instruction: nlInstruction },
    });
    setNlLoading(false);
    if (error) {
      setNlError(problemMessage(error));
      return;
    }
    setNlResult(data ?? null);
  }

  async function applyProposal(p: components["schemas"]["ProposedRuleChangeOut"]) {
    const config = p.config ?? {};
    const existing = (rulesQuery.data ?? []).find((r) => r.rule_key === p.rule_key);
    if (p.action === "edit" && existing) {
      const { error } = await api.PATCH("/v1/rules/{rule_id}", {
        params: { path: { rule_id: existing.id } },
        body: {
          name: p.name ?? existing.name, trigger_type: p.trigger_type ?? existing.trigger_type,
          config, exclusions: p.exclusions, exemption_library_code: p.exemption_code ?? null,
        },
      });
      if (error) {
        alert(problemMessage(error));
        return;
      }
    } else {
      const { error } = await api.POST("/v1/rule-set-versions/{version_id}/rules", {
        params: { path: { version_id: versionId } },
        body: {
          rule_key: p.rule_key, name: p.name ?? p.rule_key, trigger_type: p.trigger_type ?? "regex",
          config, exclusions: p.exclusions, exemption_library_code: p.exemption_code ?? null,
          source_ref: `nl-edit: ${nlInstruction}`,
          priority: 100, confidence_policy: "suggest", scope: "org",
        },
      });
      if (error) {
        alert(problemMessage(error));
        return;
      }
    }
    setNlResult((prev) => (prev ? { ...prev, proposals: prev.proposals.filter((x) => x !== p) } : prev));
    refetch();
    onVersionForked();
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-neutral-500">{rulesQuery.data?.length ?? 0} rule(s) in this version</p>
        {editing === null && (
          <Button size="sm" onClick={() => setEditing("new")}>+ New rule</Button>
        )}
      </div>

      {editing === "new" && (
        <RuleEditorForm
          initial={null}
          versionId={versionId}
          onCancel={() => setEditing(null)}
          onDone={() => { setEditing(null); refetch(); onVersionForked(); }}
        />
      )}
      {editing && editing !== "new" && (
        <RuleEditorForm
          initial={editing}
          versionId={versionId}
          onCancel={() => setEditing(null)}
          onDone={() => { setEditing(null); refetch(); onVersionForked(); }}
        />
      )}

      {rulesQuery.isLoading ? (
        <p className="text-sm text-neutral-500">Loading…</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left text-neutral-500">
                <th scope="col" className="py-1.5 pr-2 font-medium">Key</th>
                <th scope="col" className="py-1.5 pr-2 font-medium">Name</th>
                <th scope="col" className="py-1.5 pr-2 font-medium">Trigger</th>
                <th scope="col" className="py-1.5 pr-2 font-medium">Priority</th>
                <th scope="col" className="py-1.5 pr-2 font-medium">Confidence policy</th>
                <th scope="col" className="py-1.5 pr-2 font-medium">Exclusions</th>
                <th scope="col" className="py-1.5 pr-2 font-medium">Status</th>
                <th scope="col" className="py-1.5 font-medium"><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody>
              {(rulesQuery.data ?? []).map((rule) => (
                <tr key={rule.id} className="border-b last:border-0">
                  <td className="py-2 pr-2 font-mono">{rule.rule_key}</td>
                  <td className="py-2 pr-2">{rule.name}</td>
                  <td className="py-2 pr-2"><Badge variant="outline">{rule.trigger_type}</Badge></td>
                  <td className="py-2 pr-2">{rule.priority}</td>
                  <td className="py-2 pr-2">{rule.confidence_policy}</td>
                  <td className="py-2 pr-2">{rule.exclusions.length}</td>
                  <td className="py-2 pr-2"><Badge variant={rule.status === "active" ? "secondary" : "outline"}>{rule.status}</Badge></td>
                  <td className="py-2">
                    <div className="flex gap-1">
                      <Button size="xs" variant="outline" onClick={() => setEditing(rule)}>Edit</Button>
                      <Button size="xs" variant="destructive" onClick={() => handleDelete(rule)}>Delete</Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <Separator />

      <Card>
        <CardHeader><CardTitle className="text-sm">Describe a change (AI-assisted)</CardTitle></CardHeader>
        <CardContent className="flex flex-col gap-3">
          <form onSubmit={runNlEdit} className="flex flex-col gap-2">
            <Textarea
              placeholder='e.g. "Stop redacting phone numbers that appear in the letterhead" or "Add a rule for passport numbers under b(6)"'
              value={nlInstruction}
              onChange={(e) => setNlInstruction(e.target.value)}
              required
            />
            <Button type="submit" disabled={nlLoading} className="self-start">
              {nlLoading ? "Thinking…" : "Preview changes"}
            </Button>
          </form>
          {nlError && <p className="text-sm text-red-600">{nlError}</p>}
          {nlResult && (
            <div className="flex flex-col gap-2">
              {nlResult.proposals.length === 0 ? (
                <p className="text-sm text-neutral-500">No proposed changes.</p>
              ) : (
                nlResult.proposals.map((p, idx) => (
                  <div key={`${p.rule_key}-${idx}`} className="rounded-lg border p-3 text-sm">
                    <div className="flex items-center justify-between">
                      <div>
                        <Badge variant={p.action === "new" ? "secondary" : "outline"}>{p.action}</Badge>{" "}
                        <span className="font-mono font-medium">{p.rule_key}</span> — {p.name}
                      </div>
                      {p.is_valid ? (
                        <Button size="xs" onClick={() => applyProposal(p)}>Apply</Button>
                      ) : (
                        <Badge variant="destructive">invalid</Badge>
                      )}
                    </div>
                    <p className="mt-1 text-neutral-500">{p.rationale}</p>
                    {p.invalid_reason && <p className="text-red-600">{p.invalid_reason}</p>}
                    <pre className="mt-1 overflow-x-auto rounded bg-neutral-100 p-2 text-xs dark:bg-neutral-900">
                      {JSON.stringify(p.config, null, 2)}
                    </pre>
                  </div>
                ))
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function TestBenchTab({ versionId }: { versionId: string }) {
  const [selectedDocIds, setSelectedDocIds] = useState<string[]>([]);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<components["schemas"]["TestBenchResponse"] | null>(null);

  const documentsQuery = useQuery({
    queryKey: ["documents"],
    queryFn: async () => {
      const { data, error } = await api.GET("/v1/documents", {});
      if (error) throw error;
      return data;
    },
  });

  async function runTestBench() {
    setError(null);
    setRunning(true);
    const { data, error } = await api.POST("/v1/rule-set-versions/{version_id}/test", {
      params: { path: { version_id: versionId } },
      body: { document_ids: selectedDocIds },
    });
    setRunning(false);
    if (error) {
      setError(problemMessage(error));
      return;
    }
    setResult(data ?? null);
  }

  function MatchList({ title, items, tone }: { title: string; items: components["schemas"]["TestBenchMatchOut"][]; tone: "add" | "remove" | "same" }) {
    const color = tone === "add" ? "text-emerald-700" : tone === "remove" ? "text-red-600" : "text-neutral-600";
    return (
      <div>
        <p className={`mb-1 text-sm font-medium ${color}`}>{title} ({items.length})</p>
        {items.length === 0 ? (
          <p className="text-xs text-neutral-500">None</p>
        ) : (
          <ul className="flex flex-col divide-y rounded-lg border text-xs">
            {items.map((m, idx) => (
              <li key={idx} className="flex items-center justify-between px-2 py-1.5">
                <span className="font-mono">{m.rule_key}</span>
                <span className="truncate text-neutral-500">p.{m.page_no} · {m.text}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-neutral-500">
        Pick sample documents to run this draft&rsquo;s rules against, and see would-be candidates plus the diff vs the pack&rsquo;s current published version.
      </p>
      <div className="flex flex-col gap-2 rounded-lg border p-3">
        {(documentsQuery.data ?? []).length === 0 ? (
          <p className="text-sm text-neutral-500">No documents uploaded yet.</p>
        ) : (
          (documentsQuery.data ?? []).map((doc) => (
            <label key={doc.id} className="flex items-center gap-2 text-sm">
              <Checkbox
                checked={selectedDocIds.includes(doc.id)}
                onCheckedChange={(c) =>
                  setSelectedDocIds((prev) => (c ? [...prev, doc.id] : prev.filter((id) => id !== doc.id)))
                }
              />
              {doc.filename}
            </label>
          ))
        )}
      </div>
      <Button onClick={runTestBench} disabled={running || selectedDocIds.length === 0} className="self-start">
        {running ? "Running…" : "Run test bench"}
      </Button>
      {error && <p className="text-sm text-red-600">{error}</p>}
      {result && (
        <div className="flex flex-col gap-4 rounded-lg border p-3">
          <p className="text-xs text-neutral-500">
            {result.published_version_id
              ? `Diffed against published version ${result.published_version_id}`
              : "This pack has never been published — everything shown is new."}
          </p>
          <MatchList title="Added" items={result.added} tone="add" />
          <MatchList title="Removed" items={result.removed} tone="remove" />
          <MatchList title="Unchanged" items={result.unchanged} tone="same" />
        </div>
      )}
    </div>
  );
}

function VersionsTab({
  packId,
  versions,
  selectedVersionId,
  onSelectVersion,
  onChanged,
}: {
  packId: string;
  versions: components["schemas"]["RuleSetVersionOut"][];
  selectedVersionId: string | null;
  onSelectVersion: (id: string) => void;
  onChanged: () => void;
}) {
  const [changelog, setChangelog] = useState("");
  const [publishing, setPublishing] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [creatingDraft, setCreatingDraft] = useState(false);

  async function handlePublish(versionId: string) {
    setError(null);
    setPublishing(versionId);
    const { error } = await api.POST("/v1/rule-set-versions/{version_id}/publish", {
      params: { path: { version_id: versionId } },
      body: { changelog: changelog || null },
    });
    setPublishing(null);
    if (error) {
      setError(problemMessage(error));
      return;
    }
    setChangelog("");
    onChanged();
  }

  async function handleNewDraft() {
    setError(null);
    setCreatingDraft(true);
    const { data, error } = await api.POST("/v1/rule-packs/{rule_pack_id}/versions", {
      params: { path: { rule_pack_id: packId } },
    });
    setCreatingDraft(false);
    if (error) {
      setError(problemMessage(error));
      return;
    }
    onChanged();
    if (data?.id) onSelectVersion(data.id);
  }

  return (
    <div className="flex flex-col gap-4">
      <Button size="sm" onClick={handleNewDraft} disabled={creatingDraft} className="self-start">
        {creatingDraft ? "Creating…" : "+ New draft version"}
      </Button>
      {error && <p className="text-sm text-red-600">{error}</p>}
      <ul className="flex flex-col divide-y rounded-lg border">
        {versions.map((v) => (
          <li key={v.id} className="flex flex-col gap-2 px-3 py-2 text-sm">
            <div className="flex items-center justify-between">
              <button className="font-medium hover:underline" onClick={() => onSelectVersion(v.id)}>
                v{v.version} {v.id === selectedVersionId && "(selected)"}
              </button>
              <Badge variant={v.status === "published" ? "secondary" : v.status === "draft" ? "default" : "outline"}>
                {v.status}
              </Badge>
            </div>
            {v.changelog && <p className="text-xs text-neutral-500">{v.changelog}</p>}
            {v.published_at && (
              <p className="text-xs text-neutral-500">published {new Date(v.published_at).toLocaleString()}</p>
            )}
            {v.status === "draft" && (
              <div className="flex items-center gap-2">
                <Input
                  placeholder="Changelog (optional)"
                  value={v.id === selectedVersionId ? changelog : ""}
                  onChange={(e) => setChangelog(e.target.value)}
                  onFocus={() => onSelectVersion(v.id)}
                  className="max-w-xs"
                />
                <Button size="xs" onClick={() => handlePublish(v.id)} disabled={publishing === v.id}>
                  {publishing === v.id ? "Publishing…" : "Publish"}
                </Button>
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function RulePackDetailPage() {
  const router = useRouter();
  const params = useParams<{ packId: string }>();
  const packId = params.packId;
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<Tab>("rules");
  const [selectedVersionId, setSelectedVersionId] = useState<string | null>(null);

  useEffect(() => {
    if (!getToken()) router.replace("/login");
  }, [router]);

  const packsQuery = useQuery({
    queryKey: ["rule-packs"],
    queryFn: async () => {
      const { data, error } = await api.GET("/v1/rule-packs", {});
      if (error) throw error;
      return data;
    },
  });
  const pack = packsQuery.data?.find((p) => p.id === packId);

  const versionsQuery = useQuery({
    queryKey: ["rule-pack-versions", packId],
    queryFn: async () => {
      const { data, error } = await api.GET("/v1/rule-packs/{rule_pack_id}/versions", {
        params: { path: { rule_pack_id: packId } },
      });
      if (error) throw error;
      return data;
    },
  });

  const versions = useMemo(
    () => [...(versionsQuery.data ?? [])].sort((a, b) => b.version - a.version),
    [versionsQuery.data]
  );

  useEffect(() => {
    if (!selectedVersionId && versions.length > 0) {
      const draft = versions.find((v) => v.status === "draft");
      setSelectedVersionId((draft ?? versions[0]).id);
    }
  }, [versions, selectedVersionId]);

  async function refetchVersionsAndFollowDraft() {
    // Editing/deleting a rule on a published version auto-forks a new draft
    // (specs/06: "publish is immutable, edit attempt creates new draft") — jump the
    // selection there so the rules tab shows where the change actually landed, instead
    // of silently re-fetching the untouched published version the user was looking at.
    queryClient.invalidateQueries({ queryKey: ["rule-packs"] });
    const { data: fresh } = await versionsQuery.refetch();
    const sorted = [...(fresh ?? [])].sort((a, b) => b.version - a.version);
    const draft = sorted.find((v) => v.status === "draft");
    if (draft) setSelectedVersionId(draft.id);
  }

  return (
    <main id="main-content" className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-6 p-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">{pack?.name ?? "Rule pack"}</h1>
          {pack && <p className="text-sm text-neutral-500">{pack.category} · {pack.org_id ? "org-owned" : "starter pack"}</p>}
        </div>
        <Link href="/rules" className="text-sm text-neutral-500 hover:underline">← Rule packs</Link>
      </div>

      {versions.length > 0 && (
        <div className="flex items-center gap-2">
          <Label className="shrink-0">Version</Label>
          <Select
            value={selectedVersionId ?? ""}
            onValueChange={(v) => v && setSelectedVersionId(v)}
            items={Object.fromEntries(versions.map((v) => [v.id, `v${v.version} — ${v.status}`]))}
          >
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>
              {versions.map((v) => (
                <SelectItem key={v.id} value={v.id}>v{v.version} — {v.status}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}

      <Tabs value={tab} onValueChange={(v) => setTab(v as Tab)}>
        <TabsList>
          <TabsTrigger value="rules">Rules</TabsTrigger>
          <TabsTrigger value="test-bench">Test bench</TabsTrigger>
          <TabsTrigger value="versions">Versions</TabsTrigger>
        </TabsList>

        {versionsQuery.isLoading ? (
          <p className="text-sm text-neutral-500">Loading…</p>
        ) : !selectedVersionId ? (
          <p className="text-sm text-neutral-500">This pack has no versions yet.</p>
        ) : (
          <>
            <TabsPanel value="rules">
              <RulesTab versionId={selectedVersionId} onVersionForked={refetchVersionsAndFollowDraft} />
            </TabsPanel>
            <TabsPanel value="test-bench">
              <TestBenchTab versionId={selectedVersionId} />
            </TabsPanel>
            <TabsPanel value="versions">
              <VersionsTab
                packId={packId}
                versions={versions}
                selectedVersionId={selectedVersionId}
                onSelectVersion={setSelectedVersionId}
                onChanged={refetchVersionsAndFollowDraft}
              />
            </TabsPanel>
          </>
        )}
      </Tabs>
    </main>
  );
}
