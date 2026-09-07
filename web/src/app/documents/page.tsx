"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AppShell } from "@/components/app-shell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { StatusPill } from "@/components/ui/status-pill";
import { api, problemMessage } from "@/lib/api-client";
import { getToken } from "@/lib/auth";
import { cn } from "@/lib/utils";
import { FileText, Upload } from "lucide-react";

export default function DocumentsPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [rejectedEntries, setRejectedEntries] = useState<{ filename: string; reason: string }[]>([]);
  const [search, setSearch] = useState("");

  useEffect(() => {
    if (!getToken()) router.replace("/login");
  }, [router]);

  const documentsQuery = useQuery({
    queryKey: ["documents"],
    queryFn: async () => {
      const { data, error } = await api.GET("/v1/documents", {});
      if (error) throw error;
      return data;
    },
    refetchInterval: 4000, // cheap polling for Phase 1's synchronous-but-not-instant processing
  });

  // Resolves DocumentOut.uploaded_by (a bare user id) to a display name for the grid -
  // one membership list fetch, cached, rather than a name lookup per document card.
  const membersQuery = useQuery({
    queryKey: ["members"],
    queryFn: async () => {
      const { data, error } = await api.GET("/v1/orgs/current/members", {});
      if (error) throw error;
      return data;
    },
  });
  const nameByUserId = useMemo(() => {
    const map = new Map<string, string>();
    for (const m of membersQuery.data ?? []) map.set(m.user_id, m.name);
    return map;
  }, [membersQuery.data]);

  const filteredDocuments = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return documentsQuery.data ?? [];
    return (documentsQuery.data ?? []).filter((doc) => doc.filename.toLowerCase().includes(q));
  }, [documentsQuery.data, search]);

  async function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    setUploadError(null);
    setRejectedEntries([]);
    const { data, error } = await api.POST("/v1/documents", {
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
    // ZIP batches: some entries may fail validation without failing the whole upload
    // (specs/05-redaction-pipeline.md Stage 1) — surface them instead of dropping silently.
    if (data?.rejected?.length) setRejectedEntries(data.rejected);
    queryClient.invalidateQueries({ queryKey: ["documents"] });
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  return (
    <AppShell>
      <main id="main-content" className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-6 p-8">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-xl font-semibold">Documents</h1>
            <p className="text-xs text-neutral-500">
              Accepts PDF, ZIP of PDFs, and .eml/.msg. For Word/Excel/PowerPoint files, export to PDF first.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <input
              ref={fileInputRef}
              type="file"
              accept="application/pdf,.zip,application/zip"
              className="hidden"
              onChange={handleFileChange}
            />
            <Button onClick={() => fileInputRef.current?.click()} disabled={uploading}>
              <Upload className="size-4" aria-hidden />
              {uploading ? "Uploading…" : "Upload document or ZIP batch"}
            </Button>
          </div>
        </div>

        {uploadError && <p role="alert" className="text-sm text-red-600">{uploadError}</p>}
        {rejectedEntries.length > 0 && (
          <div role="status" aria-live="polite" className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-800">
            <p className="font-medium">{rejectedEntries.length} file(s) in the ZIP were skipped:</p>
            <ul className="mt-1 list-disc pl-5">
              {rejectedEntries.map((entry) => (
                <li key={entry.filename}>
                  {entry.filename} — {entry.reason}
                </li>
              ))}
            </ul>
          </div>
        )}

        {(documentsQuery.data?.length ?? 0) > 0 && (
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search documents by name…"
            className="max-w-sm"
            aria-label="Search documents by name"
          />
        )}

        {documentsQuery.isLoading ? (
          <p className="text-sm text-neutral-500">Loading…</p>
        ) : documentsQuery.data?.length === 0 ? (
          <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed p-12 text-center">
            <FileText className="size-8 text-neutral-400" aria-hidden />
            <p className="text-sm text-neutral-500">No documents yet — upload a PDF to try the redaction pipeline.</p>
          </div>
        ) : filteredDocuments.length === 0 ? (
          <p className="text-sm text-neutral-500">No documents match &ldquo;{search}&rdquo;.</p>
        ) : (
          // Every document lives in this single unpaginated grid (the API has no
          // limit/offset on GET /documents) so there is never a second page to click
          // into - scrolling this grid is all that's ever needed to see the rest.
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {filteredDocuments.map((doc) => (
              <Link
                key={doc.id}
                href={`/documents/${doc.id}/review`}
                className={cn(
                  "group flex flex-col gap-3 rounded-xl border bg-card p-4 text-left transition-all hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50",
                  doc.status === "error" && "border-red-200"
                )}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-center gap-2 overflow-hidden">
                    <FileText className="size-4 shrink-0 text-neutral-400" aria-hidden />
                    <span className="truncate font-medium" title={doc.filename}>{doc.filename}</span>
                  </div>
                  <StatusPill status={doc.status} className="shrink-0" />
                </div>
                <div className="flex flex-1 flex-col gap-1 text-xs text-neutral-500">
                  <span>Uploaded by {nameByUserId.get(doc.uploaded_by) ?? "—"}</span>
                  <span>{new Date(doc.created_at).toLocaleString()}</span>
                  <span>{doc.page_count ?? "?"} page(s)</span>
                </div>
                {doc.status === "error" && doc.error && (
                  <p className="truncate text-xs text-red-600">{JSON.stringify(doc.error)}</p>
                )}
              </Link>
            ))}
          </div>
        )}
      </main>
    </AppShell>
  );
}
