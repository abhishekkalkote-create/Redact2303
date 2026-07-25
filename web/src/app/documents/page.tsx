"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api, problemMessage } from "@/lib/api-client";
import { getToken } from "@/lib/auth";

const STATUS_VARIANT: Record<string, "default" | "secondary" | "outline" | "destructive"> = {
  ready_for_review: "default",
  in_review: "default",
  review_complete: "secondary",
  exported: "secondary",
  error: "destructive",
};

export default function DocumentsPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [rejectedEntries, setRejectedEntries] = useState<{ filename: string; reason: string }[]>([]);

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
    <main className="mx-auto flex w-full max-w-4xl flex-1 flex-col gap-6 p-8">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Documents</h1>
        <div className="flex items-center gap-2">
          <Link href="/rules" className="text-sm text-neutral-500 hover:underline">
            Rules & Policies
          </Link>
          <input
            ref={fileInputRef}
            type="file"
            accept="application/pdf,.zip,application/zip"
            className="hidden"
            onChange={handleFileChange}
          />
          <Button onClick={() => fileInputRef.current?.click()} disabled={uploading}>
            {uploading ? "Uploading…" : "Upload document or ZIP batch"}
          </Button>
        </div>
      </div>
      <p className="text-xs text-neutral-500">
        Accepts PDF, ZIP of PDFs, and .eml/.msg. For Word/Excel/PowerPoint files, export
        to PDF from that application first, then upload the PDF.
      </p>
      {uploadError && <p className="text-sm text-red-600">{uploadError}</p>}
      {rejectedEntries.length > 0 && (
        <div className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-800">
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

      <Card>
        <CardHeader>
          <CardTitle>All documents</CardTitle>
        </CardHeader>
        <CardContent>
          {documentsQuery.isLoading ? (
            <p className="text-sm text-neutral-500">Loading…</p>
          ) : documentsQuery.data?.length === 0 ? (
            <p className="text-sm text-neutral-500">
              No documents yet — upload a PDF to try the redaction pipeline.
            </p>
          ) : (
            <ul className="flex flex-col divide-y">
              {documentsQuery.data?.map((doc) => (
                <li key={doc.id} className="flex items-center justify-between py-3">
                  <div>
                    <Link href={`/documents/${doc.id}/review`} className="font-medium hover:underline">
                      {doc.filename}
                    </Link>
                    <p className="text-xs text-neutral-500">
                      {doc.page_count ?? "?"} pages · uploaded {new Date(doc.created_at).toLocaleString()}
                    </p>
                    {doc.status === "error" && doc.error && (
                      <p className="text-xs text-red-600">{JSON.stringify(doc.error)}</p>
                    )}
                  </div>
                  <Badge variant={STATUS_VARIANT[doc.status] ?? "outline"}>{doc.status}</Badge>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </main>
  );
}
