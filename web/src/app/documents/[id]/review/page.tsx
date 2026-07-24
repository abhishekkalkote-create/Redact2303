"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Textarea } from "@/components/ui/textarea";
import { api, problemMessage } from "@/lib/api-client";
import { getToken } from "@/lib/auth";
import type { components } from "@redactproof/shared";

type Candidate = components["schemas"]["CandidateOut"];

const STATE_COLOR: Record<string, string> = {
  suggested: "border-amber-500 bg-amber-500/10",
  approved: "border-emerald-600 bg-emerald-600/20",
  rejected: "border-neutral-400 bg-neutral-400/10 opacity-50",
  modified: "border-blue-500 bg-blue-500/10",
};

const EXPORT_TYPES = [
  { key: "clean_pdf", label: "Clean release PDF" },
  { key: "annotated_pdf", label: "Annotated PDF (shows codes)" },
  { key: "exemption_log_csv", label: "Exemption log (CSV)" },
  { key: "certificate_pdf", label: "Redaction certificate" },
];

export default function ReviewPage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const docId = params.id;
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!getToken()) router.replace("/login");
  }, [router]);

  const [pageNo, setPageNo] = useState(1);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [imgSize, setImgSize] = useState<{ w: number; h: number } | null>(null);
  const [exportTypes, setExportTypes] = useState<string[]>(["clean_pdf", "exemption_log_csv", "certificate_pdf"]);
  const [actionError, setActionError] = useState<string | null>(null);
  const [exportResult, setExportResult] = useState<components["schemas"]["ExportOut"][] | null>(null);
  const imgRef = useRef<HTMLImageElement>(null);

  const docQuery = useQuery({
    queryKey: ["document", docId],
    queryFn: async () => {
      const { data, error } = await api.GET("/v1/documents/{doc_id}", { params: { path: { doc_id: docId } } });
      if (error) throw error;
      return data;
    },
  });

  const pagesQuery = useQuery({
    queryKey: ["pages", docId],
    queryFn: async () => {
      const { data, error } = await api.GET("/v1/documents/{doc_id}/pages", { params: { path: { doc_id: docId } } });
      if (error) throw error;
      return data;
    },
    enabled: !!docQuery.data,
  });

  const manifestQuery = useQuery({
    queryKey: ["manifest", docId],
    queryFn: async () => {
      const { data, error } = await api.GET("/v1/documents/{doc_id}/manifest", { params: { path: { doc_id: docId } } });
      if (error) throw error;
      return data;
    },
    enabled: !!docQuery.data,
  });

  const codesQuery = useQuery({
    queryKey: ["exemption-codes"],
    queryFn: async () => {
      const { data, error } = await api.GET("/v1/exemption-codes", {});
      if (error) throw error;
      return data;
    },
  });

  useEffect(() => {
    let currentUrl: string | null = null;
    async function loadImage() {
      const { data } = await api.GET("/v1/documents/{doc_id}/pages/{page_no}/preview", {
        params: { path: { doc_id: docId, page_no: pageNo } },
        parseAs: "blob",
      });
      if (data instanceof Blob) {
        currentUrl = URL.createObjectURL(data);
        setImageUrl(currentUrl);
      }
    }
    loadImage();
    return () => {
      if (currentUrl) URL.revokeObjectURL(currentUrl);
    };
  }, [docId, pageNo]);

  const pageCandidates = useMemo(
    () => (manifestQuery.data?.candidates ?? []).filter((c) => c.page_no === pageNo),
    [manifestQuery.data, pageNo]
  );
  const selected = pageCandidates.find((c) => c.id === selectedId) ?? null;
  const currentPageMeta = pagesQuery.data?.find((p) => p.page_no === pageNo);

  const lowConfidenceUnresolved = (manifestQuery.data?.candidates ?? []).filter(
    (c) => c.state === "suggested" && c.confidence === "low"
  ).length;

  const refetchManifest = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ["manifest", docId] });
  }, [queryClient, docId]);

  const decide = useCallback(
    async (candidate: Candidate, state: "approved" | "rejected") => {
      setActionError(null);
      const { error } = await api.PATCH("/v1/candidates/{candidate_id}", {
        params: { path: { candidate_id: candidate.id } },
        body: { state, exemption_code_id: candidate.exemption_code_id ?? undefined },
      });
      if (error) {
        setActionError(problemMessage(error));
        return;
      }
      refetchManifest();
    },
    [refetchManifest]
  );

  async function updateCode(candidate: Candidate, codeId: string) {
    setActionError(null);
    const { error } = await api.PATCH("/v1/candidates/{candidate_id}", {
      params: { path: { candidate_id: candidate.id } },
      body: { exemption_code_id: codeId },
    });
    if (error) {
      setActionError(problemMessage(error));
      return;
    }
    refetchManifest();
  }

  async function applyToSimilar(candidate: Candidate, action: "approve" | "reject") {
    if (!candidate.recurrence_group_id) return;
    setActionError(null);
    const { error } = await api.POST("/v1/documents/{doc_id}/candidates:bulk", {
      params: { path: { doc_id: docId } },
      body: {
        action,
        recurrence_group_id: candidate.recurrence_group_id,
        exemption_code_id: action === "approve" ? candidate.exemption_code_id ?? undefined : undefined,
      },
    });
    if (error) {
      setActionError(problemMessage(error));
      return;
    }
    refetchManifest();
  }

  async function saveJustification(candidate: Candidate, text: string) {
    await api.PATCH("/v1/candidates/{candidate_id}", {
      params: { path: { candidate_id: candidate.id } },
      body: { ai_justification: text },
    });
    refetchManifest();
  }

  const selectNextCandidate = useCallback(() => {
    const idx = pageCandidates.findIndex((c) => c.id === selectedId);
    const next = pageCandidates[idx + 1] ?? pageCandidates[0];
    setSelectedId(next?.id ?? null);
  }, [pageCandidates, selectedId]);

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (!selected) return;
      if (e.target instanceof HTMLTextAreaElement || e.target instanceof HTMLInputElement) return;
      if (e.key.toLowerCase() === "a") decide(selected, "approved");
      if (e.key.toLowerCase() === "r") decide(selected, "rejected");
      if (e.key.toLowerCase() === "n") selectNextCandidate();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [selected, pageCandidates, selectedId, decide, selectNextCandidate]);

  async function handleCompleteReview() {
    setActionError(null);
    const { error } = await api.POST("/v1/documents/{doc_id}/review:complete", {
      params: { path: { doc_id: docId } },
    });
    if (error) {
      setActionError(problemMessage(error));
      return;
    }
    queryClient.invalidateQueries({ queryKey: ["document", docId] });
  }

  async function downloadArtifact(artifactId: string, filename: string) {
    // A plain <a href> won't carry the Authorization header the org-scoped download
    // endpoint requires — fetch it via the authenticated client and save the blob instead.
    const { data, error } = await api.GET("/v1/exports/{export_id}/download", {
      params: { path: { export_id: artifactId } },
      parseAs: "blob",
    });
    if (error || !(data instanceof Blob)) {
      setActionError(problemMessage(error));
      return;
    }
    const url = URL.createObjectURL(data);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    link.click();
    URL.revokeObjectURL(url);
  }

  async function handleExport() {
    setActionError(null);
    setExportResult(null);
    const { data, error } = await api.POST("/v1/documents/{doc_id}/exports", {
      params: { path: { doc_id: docId } },
      body: { types: exportTypes },
    });
    if (error) {
      setActionError(problemMessage(error));
      return;
    }
    setExportResult(data ?? []);
    queryClient.invalidateQueries({ queryKey: ["document", docId] });
  }

  if (docQuery.isLoading) return <main className="p-8 text-sm text-neutral-500">Loading…</main>;
  if (!docQuery.data) return null;
  const doc = docQuery.data;

  const scale = imgSize && currentPageMeta ? imgSize.w / currentPageMeta.width : 1;

  return (
    <main className="flex h-screen flex-col">
      <div className="flex items-center justify-between border-b p-3">
        <div>
          <span className="font-medium">{doc.filename}</span>{" "}
          <Badge variant="outline" className="ml-2">{doc.status}</Badge>
          <span className="ml-2 text-xs text-neutral-500">manifest v{manifestQuery.data?.version}</span>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" onClick={handleCompleteReview} disabled={doc.status !== "ready_for_review" && doc.status !== "in_review"}>
            Complete review
          </Button>
        </div>
      </div>
      {actionError && <p className="border-b bg-red-50 p-2 text-sm text-red-600">{actionError}</p>}

      <div className="flex flex-1 overflow-hidden">
        {/* Left rail: page list */}
        <aside className="w-48 overflow-y-auto border-r p-2">
          {pagesQuery.data?.map((p) => {
            const count = (manifestQuery.data?.candidates ?? []).filter((c) => c.page_no === p.page_no).length;
            return (
              <button
                key={p.page_no}
                onClick={() => { setPageNo(p.page_no); setSelectedId(null); }}
                className={`mb-1 flex w-full items-center justify-between rounded px-2 py-1.5 text-sm ${p.page_no === pageNo ? "bg-neutral-200 dark:bg-neutral-800" : "hover:bg-neutral-100 dark:hover:bg-neutral-900"}`}
              >
                <span>Page {p.page_no}</span>
                {count > 0 && <Badge variant="secondary">{count}</Badge>}
              </button>
            );
          })}
        </aside>

        {/* Center: viewer */}
        <section className="flex-1 overflow-auto bg-neutral-100 p-4 dark:bg-neutral-950">
          {imageUrl && currentPageMeta && (
            <div className="relative mx-auto w-fit">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                ref={imgRef}
                src={imageUrl}
                alt={`Page ${pageNo}`}
                className="block max-w-full shadow"
                onLoad={(e) => setImgSize({ w: e.currentTarget.clientWidth, h: e.currentTarget.clientHeight })}
              />
              {imgSize &&
                pageCandidates.map((c) => (
                  <button
                    key={c.id}
                    onClick={() => setSelectedId(c.id)}
                    className={`absolute border-2 ${STATE_COLOR[c.state] ?? "border-neutral-400"} ${selectedId === c.id ? "ring-2 ring-blue-500" : ""}`}
                    style={{
                      left: c.bbox.x * scale,
                      top: c.bbox.y * scale,
                      width: c.bbox.w * scale,
                      height: c.bbox.h * scale,
                    }}
                    title={c.exemption_code ?? ""}
                  />
                ))}
            </div>
          )}
        </section>

        {/* Right panel: candidate detail */}
        <aside className="w-96 overflow-y-auto border-l p-4">
          {selected ? (
            <div className="flex flex-col gap-3">
              <div>
                <p className="text-xs text-neutral-500">Extracted text</p>
                <p className="rounded bg-neutral-100 p-2 font-mono text-sm dark:bg-neutral-900">{selected.display_text}</p>
              </div>
              <div className="flex items-center gap-2">
                <Badge>{selected.confidence}</Badge>
                <Badge variant="outline">{selected.origin}</Badge>
                <Badge variant="secondary">{selected.state}</Badge>
              </div>
              <div>
                <p className="mb-1 text-xs text-neutral-500">Exemption code</p>
                <Select
                  value={selected.exemption_code_id ?? undefined}
                  onValueChange={(v) => v && updateCode(selected, v)}
                >
                  <SelectTrigger><SelectValue placeholder="Choose a code…" /></SelectTrigger>
                  <SelectContent>
                    {codesQuery.data?.map((code) => (
                      <SelectItem key={code.id} value={code.id}>
                        {code.code} — {code.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              {selected.ai_justification !== null && (
                <div>
                  <p className="mb-1 text-xs text-neutral-500">AI justification (editable)</p>
                  <Textarea
                    defaultValue={selected.ai_justification ?? ""}
                    onBlur={(e) => saveJustification(selected, e.target.value)}
                  />
                </div>
              )}
              <div className="flex gap-2">
                <Button onClick={() => decide(selected, "approved")} disabled={!selected.exemption_code_id}>
                  Approve (A)
                </Button>
                <Button variant="outline" onClick={() => decide(selected, "rejected")}>
                  Reject (R)
                </Button>
              </div>
              {selected.recurrence_group_id && (
                <div className="rounded border p-2 text-sm">
                  <p className="mb-1 text-neutral-500">
                    Appears {(manifestQuery.data?.candidates ?? []).filter((c) => c.recurrence_group_id === selected.recurrence_group_id).length}× in this document
                  </p>
                  <Button size="sm" variant="outline" onClick={() => applyToSimilar(selected, "approve")} disabled={!selected.exemption_code_id}>
                    Apply to all similar
                  </Button>
                </div>
              )}
              <Separator />
              <Button variant="ghost" size="sm" onClick={selectNextCandidate}>Next candidate (N)</Button>
            </div>
          ) : (
            <p className="text-sm text-neutral-500">
              Select a highlighted region to review it. {pageCandidates.length} candidate(s) on this page.
            </p>
          )}
        </aside>
      </div>

      <div className="flex items-center justify-between border-t p-3 text-sm">
        <span className="text-neutral-500">
          {lowConfidenceUnresolved > 0
            ? `${lowConfidenceUnresolved} low-confidence candidate(s) unresolved`
            : "All low-confidence candidates resolved"}
          {" · "}Shortcuts: A approve · R reject · N next
        </span>
        {doc.status === "review_complete" && (
          <div className="flex items-center gap-3">
            {EXPORT_TYPES.map((t) => (
              <label key={t.key} className="flex items-center gap-1 text-xs">
                <Checkbox
                  checked={exportTypes.includes(t.key)}
                  onCheckedChange={(checked) =>
                    setExportTypes((prev) => (checked ? [...prev, t.key] : prev.filter((x) => x !== t.key)))
                  }
                />
                {t.label}
              </label>
            ))}
            <Button onClick={handleExport}>Export</Button>
          </div>
        )}
      </div>

      {exportResult && (
        <div className="border-t bg-neutral-50 p-3 text-sm dark:bg-neutral-900">
          <p className="mb-1 font-medium">Export complete:</p>
          <ul className="flex flex-col gap-1">
            {exportResult.map((artifact) => (
              <li key={artifact.id}>
                <button
                  className="text-blue-600 hover:underline"
                  onClick={() => downloadArtifact(artifact.id, `${doc.filename}-${artifact.type}`)}
                >
                  {artifact.type}
                </button>{" "}
                — integrity {artifact.integrity_check.passed ? "✓ passed" : "✗ FAILED"}
              </li>
            ))}
          </ul>
        </div>
      )}
    </main>
  );
}
