"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Dialog } from "@base-ui/react/dialog";
import { Download, ExternalLink, X } from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { StatusPill } from "@/components/ui/status-pill";
import { Textarea } from "@/components/ui/textarea";
import { Tabs, TabsList, TabsPanel, TabsTrigger } from "@/components/ui/tabs";
import { api, problemMessage } from "@/lib/api-client";
import { getToken } from "@/lib/auth";
import { cn } from "@/lib/utils";
import type { components } from "@redactproof/shared";

type Candidate = components["schemas"]["CandidateOut"];
type PageMeta = components["schemas"]["PageOut"];
type BBoxT = components["schemas"]["BBox"];

// Accessibility: color alone must never be the only way to tell states apart (WCAG
// 1.4.1) — border style (solid/dashed/dotted), not just hue, distinguishes these on the
// page overlay; the side panel also repeats state as a text Badge (see `selected.state`
// below) for whichever candidate is selected.
const STATE_COLOR: Record<string, string> = {
  suggested: "border-solid border-amber-500 bg-amber-500/10",
  approved: "border-solid border-emerald-600 bg-emerald-600/20",
  rejected: "border-dashed border-neutral-400 bg-neutral-400/10 opacity-50",
  modified: "border-dotted border-blue-500 bg-blue-500/10",
};

// specs/05-redaction-pipeline.md Stage 2: "pages < 0.6 flagged... never mark such pages
// auto-complete" — matches LOW_OCR_CONFIDENCE_THRESHOLD in api/app/services/review_service.py,
// which actually enforces the block; this just surfaces the same signal to the reviewer.
const LOW_OCR_CONFIDENCE_THRESHOLD = 0.6;

// A drag smaller than this (in on-screen pixels) is treated as an accidental click, not
// a deliberate "select this text to redact" gesture.
const MIN_DRAG_SIZE = 8;

const EXPORT_TYPES = [
  { key: "clean_pdf", label: "Clean release PDF" },
  { key: "annotated_pdf", label: "Annotated PDF (shows codes)" },
  { key: "exemption_log_csv", label: "Exemption log (CSV)" },
  { key: "certificate_pdf", label: "Redaction certificate" },
];

// Every export type maps to a real file extension - artifact.type (e.g. "clean_pdf",
// "exemption_log_csv") is a schema/routing identifier, not a filename suffix, so using it
// raw (as this used to) produced downloads like "report.pdf-clean_pdf" with no extension
// the OS/browser could recognize.
const EXPORT_FILE_INFO: Record<string, { suffix: string; ext: string }> = {
  clean_pdf: { suffix: "clean", ext: "pdf" },
  annotated_pdf: { suffix: "annotated", ext: "pdf" },
  certificate_pdf: { suffix: "certificate", ext: "pdf" },
  exemption_log_csv: { suffix: "exemption-log", ext: "csv" },
  exemption_log_pdf: { suffix: "exemption-log", ext: "pdf" },
  exemption_log_json: { suffix: "exemption-log", ext: "json" },
};

function exportFilename(originalFilename: string, artifactType: string): string {
  const base = originalFilename.replace(/\.[^./\\]+$/, "");
  const info = EXPORT_FILE_INFO[artifactType];
  return info ? `${base}-${info.suffix}.${info.ext}` : `${base}-${artifactType}`;
}

/** True once `ref`'s element has ever intersected the viewport, and stays true after -
 * used to lazy-load each page's preview image only as the reviewer scrolls near it,
 * without ever unloading an already-loaded page (typical Phase-1 document lengths don't
 * need full virtualization; this just avoids fetching every page image up front). */
function useInView(ref: React.RefObject<HTMLElement | null>, rootMargin: string): boolean {
  const [inView, setInView] = useState(false);
  useEffect(() => {
    if (inView) return;
    const el = ref.current;
    if (!el) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) {
          setInView(true);
          observer.disconnect();
        }
      },
      { rootMargin }
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [ref, rootMargin, inView]);
  return inView;
}

interface DragRect {
  x: number;
  y: number;
  w: number;
  h: number;
}

interface PendingSelection {
  screenRect: DragRect;
  bboxPdf: BBoxT;
}

function PageView({
  docId,
  page,
  candidates,
  viewMode,
  selectedId,
  codes,
  onSelectCandidate,
  onCreateManual,
  registerRef,
}: {
  docId: string;
  page: PageMeta;
  candidates: Candidate[];
  viewMode: "original" | "preview";
  selectedId: string | null;
  codes: components["schemas"]["ExemptionCodeOut"][] | undefined;
  onSelectCandidate: (id: string, pageNo: number) => void;
  onCreateManual: (pageNo: number, bbox: BBoxT, exemptionCodeId: string) => Promise<void>;
  registerRef: (pageNo: number, el: HTMLDivElement | null) => void;
}) {
  const wrapperRef = useRef<HTMLDivElement>(null);
  const inView = useInView(wrapperRef, "800px 0px");
  const [imgUrl, setImgUrl] = useState<string | null>(null);
  const [imgSize, setImgSize] = useState<{ w: number; h: number } | null>(null);
  const [drag, setDrag] = useState<DragRect | null>(null);
  const [pending, setPending] = useState<PendingSelection | null>(null);
  const [pendingCodeId, setPendingCodeId] = useState<string | undefined>(undefined);
  const [creating, setCreating] = useState(false);
  const dragOriginRef = useRef<{ x: number; y: number } | null>(null);

  useEffect(() => {
    if (!inView) return;
    let cancelled = false;
    let url: string | null = null;
    (async () => {
      const { data } = await api.GET("/v1/documents/{doc_id}/pages/{page_no}/preview", {
        params: { path: { doc_id: docId, page_no: page.page_no } },
        parseAs: "blob",
      });
      if (!cancelled && data instanceof Blob) {
        url = URL.createObjectURL(data);
        setImgUrl(url);
      }
    })();
    return () => {
      cancelled = true;
      if (url) URL.revokeObjectURL(url);
    };
  }, [inView, docId, page.page_no]);

  const scale = imgSize ? imgSize.w / page.width : 1;
  const lowOcr = page.ocr_confidence != null && page.ocr_confidence < LOW_OCR_CONFIDENCE_THRESHOLD;

  function localPoint(e: React.MouseEvent) {
    const rect = wrapperRef.current!.getBoundingClientRect();
    return { x: e.clientX - rect.left, y: e.clientY - rect.top };
  }

  function handleMouseDown(e: React.MouseEvent) {
    if (viewMode !== "original") return;
    if (e.button !== 0) return;
    if ((e.target as HTMLElement).closest("button")) return; // don't start a drag on top of an existing candidate box
    const p = localPoint(e);
    dragOriginRef.current = p;
    setDrag({ x: p.x, y: p.y, w: 0, h: 0 });
  }

  function handleMouseMove(e: React.MouseEvent) {
    if (!dragOriginRef.current) return;
    const p = localPoint(e);
    const origin = dragOriginRef.current;
    setDrag({
      x: Math.min(origin.x, p.x),
      y: Math.min(origin.y, p.y),
      w: Math.abs(p.x - origin.x),
      h: Math.abs(p.y - origin.y),
    });
  }

  function handleMouseUp() {
    const finalDrag = drag;
    dragOriginRef.current = null;
    setDrag(null);
    if (!finalDrag || finalDrag.w < MIN_DRAG_SIZE || finalDrag.h < MIN_DRAG_SIZE) return;
    setPending({
      screenRect: finalDrag,
      bboxPdf: { x: finalDrag.x / scale, y: finalDrag.y / scale, w: finalDrag.w / scale, h: finalDrag.h / scale },
    });
    setPendingCodeId(undefined);
  }

  async function confirmPending() {
    if (!pending || !pendingCodeId) return;
    setCreating(true);
    await onCreateManual(page.page_no, pending.bboxPdf, pendingCodeId);
    setCreating(false);
    setPending(null);
  }

  const visibleCandidates = viewMode === "preview" ? candidates.filter((c) => c.state === "approved") : candidates;

  return (
    <div
      key={page.page_no}
      ref={(el) => {
        registerRef(page.page_no, el);
      }}
      data-page-no={page.page_no}
      className="mx-auto flex w-fit flex-col items-center gap-2"
    >
      <p className="text-xs font-medium text-neutral-500">Page {page.page_no}</p>
      {lowOcr && viewMode === "original" && (
        <div role="status" aria-live="polite" className="w-fit max-w-xl rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-800">
          <p className="font-medium">
            Low OCR quality — review manually ({Math.round((page.ocr_confidence ?? 0) * 100)}% confidence). This
            page cannot be marked complete until reviewed.
          </p>
        </div>
      )}
      <div
        ref={wrapperRef}
        className={cn("relative w-fit select-none", viewMode === "original" && "cursor-crosshair")}
        style={imgSize ? undefined : { minHeight: 400, minWidth: 300 }}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
      >
        {imgUrl ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={imgUrl}
            alt={`Page ${page.page_no}`}
            className="block max-w-full shadow"
            onLoad={(e) => setImgSize({ w: e.currentTarget.clientWidth, h: e.currentTarget.clientHeight })}
          />
        ) : (
          <div className="flex h-96 w-[600px] max-w-full items-center justify-center rounded border border-dashed bg-neutral-50 text-xs text-neutral-400 dark:bg-neutral-900">
            {inView ? "Loading page…" : ""}
          </div>
        )}

        {imgSize &&
          visibleCandidates.map((c) =>
            viewMode === "preview" ? (
              <div
                key={c.id}
                aria-label={`Redacted: ${c.exemption_code ?? ""}`}
                className="absolute bg-black"
                style={{ left: c.bbox.x * scale, top: c.bbox.y * scale, width: c.bbox.w * scale, height: c.bbox.h * scale }}
              />
            ) : (
              <button
                key={c.id}
                onClick={() => onSelectCandidate(c.id, page.page_no)}
                aria-label={`Candidate: ${c.display_text || "(no text)"}, ${c.state}${c.exemption_code ? `, ${c.exemption_code}` : ""}`}
                aria-pressed={selectedId === c.id}
                className={cn(
                  "absolute border-2",
                  STATE_COLOR[c.state] ?? "border-neutral-400",
                  selectedId === c.id && "ring-2 ring-blue-500"
                )}
                style={{ left: c.bbox.x * scale, top: c.bbox.y * scale, width: c.bbox.w * scale, height: c.bbox.h * scale }}
              />
            )
          )}

        {drag && (
          <div
            className="absolute border-2 border-dashed border-blue-500 bg-blue-500/20"
            style={{ left: drag.x, top: drag.y, width: drag.w, height: drag.h }}
          />
        )}
        {pending && (
          <div
            className="absolute border-2 border-dashed border-blue-500 bg-blue-500/20"
            style={{ left: pending.screenRect.x, top: pending.screenRect.y, width: pending.screenRect.w, height: pending.screenRect.h }}
          />
        )}

        {pending && imgSize && (
          <div
            className="absolute z-10 flex w-64 flex-col gap-2 rounded-lg border bg-popover p-3 text-popover-foreground shadow-lg"
            style={{
              // Anchored just below/right of the drag rectangle rather than after the
              // whole page image in document flow - a tall page (this is a continuous-
              // scroll viewer, pages can run well past one screen) previously pushed this
              // panel far below the fold, out of view right where the reviewer just acted.
              left: Math.min(pending.screenRect.x, Math.max(imgSize.w - 256, 0)),
              top: Math.min(pending.screenRect.y + pending.screenRect.h + 8, Math.max(imgSize.h - 180, 0)),
            }}
          >
            <div className="flex items-center justify-between">
              <p className="text-sm font-medium">New redaction</p>
              <button onClick={() => setPending(null)} aria-label="Cancel selection" className="text-neutral-400 hover:text-neutral-600">
                <X className="size-4" />
              </button>
            </div>
            <Select value={pendingCodeId} onValueChange={(v) => v && setPendingCodeId(v)}>
              <SelectTrigger>
                <SelectValue placeholder="Choose an exemption code…" />
              </SelectTrigger>
              <SelectContent>
                {codes?.map((code) => (
                  <SelectItem key={code.id} value={code.id}>
                    {code.code} — {code.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <div className="flex justify-end gap-2">
              <Button variant="outline" size="sm" onClick={() => setPending(null)}>
                Cancel
              </Button>
              <Button size="sm" onClick={confirmPending} disabled={!pendingCodeId || creating}>
                {creating ? "Adding…" : "Redact selection"}
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default function ReviewPage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const docId = params.id;
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!getToken()) router.replace("/login");
  }, [router]);

  const [activePageNo, setActivePageNo] = useState(1);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<"original" | "preview">("original");
  const [exportTypes, setExportTypes] = useState<string[]>(["clean_pdf", "exemption_log_csv", "certificate_pdf"]);
  const [actionError, setActionError] = useState<string | null>(null);
  const [rightTab, setRightTab] = useState<"review" | "exports">("review");
  const [previewArtifact, setPreviewArtifact] = useState<{ url: string; filename: string } | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchScope, setSearchScope] = useState<"page" | "document">("document");
  const [searchCodeId, setSearchCodeId] = useState<string | undefined>(undefined);
  const [searchStatus, setSearchStatus] = useState<string | null>(null);
  const [searching, setSearching] = useState(false);

  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const pageRefs = useRef<Map<number, HTMLDivElement>>(new Map());

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

  // Persistent per-document export history (specs/07-ui-spec.md screen 4/5: the
  // reviewer should always be able to see and re-download past exports, not only the
  // result of whichever export they just triggered this session).
  const exportsQuery = useQuery({
    queryKey: ["exports", "doc", docId],
    queryFn: async () => {
      const { data, error } = await api.GET("/v1/exports", { params: { query: { doc_id: docId } } });
      if (error) throw error;
      return data;
    },
  });

  // Sorted document-order (page, then top-to-bottom on the page) — used for "N next
  // candidate" now that every page is visible at once via continuous scroll, instead of
  // only cycling within whichever single page used to be displayed.
  const allCandidatesSorted = useMemo(
    () => [...(manifestQuery.data?.candidates ?? [])].sort((a, b) => a.page_no - b.page_no || a.bbox.y - b.bbox.y),
    [manifestQuery.data]
  );
  const candidatesByPage = useMemo(() => {
    const map = new Map<number, Candidate[]>();
    for (const c of allCandidatesSorted) {
      const list = map.get(c.page_no) ?? [];
      list.push(c);
      map.set(c.page_no, list);
    }
    return map;
  }, [allCandidatesSorted]);

  const selected = allCandidatesSorted.find((c) => c.id === selectedId) ?? null;

  const selectedCodeLabel = useMemo(() => {
    const code = codesQuery.data?.find((c) => c.id === selected?.exemption_code_id);
    return code ? `${code.code} — ${code.label}` : undefined;
  }, [codesQuery.data, selected?.exemption_code_id]);

  const lowConfidenceUnresolved = (manifestQuery.data?.candidates ?? []).filter(
    (c) => c.state === "suggested" && c.confidence === "low"
  ).length;

  const refetchManifest = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ["manifest", docId] });
  }, [queryClient, docId]);

  function registerPageRef(pageNo: number, el: HTMLDivElement | null) {
    if (el) pageRefs.current.set(pageNo, el);
    else pageRefs.current.delete(pageNo);
  }

  function scrollToPage(pageNo: number) {
    setActivePageNo(pageNo);
    pageRefs.current.get(pageNo)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  // Highlights whichever page is most visible in the scroll container as the "current"
  // page in the left rail — the reviewer scrolling continuously through the document
  // (rather than clicking a page number every time) is exactly requirement #7: page 2
  // should appear by scrolling, not by requiring an extra click.
  useEffect(() => {
    const root = scrollContainerRef.current;
    if (!root || !pagesQuery.data?.length) return;
    const observer = new IntersectionObserver(
      (entries) => {
        let best: { pageNo: number; ratio: number } | null = null;
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          const pageNo = Number((entry.target as HTMLElement).dataset.pageNo);
          if (!best || entry.intersectionRatio > best.ratio) best = { pageNo, ratio: entry.intersectionRatio };
        }
        if (best) setActivePageNo(best.pageNo);
      },
      { root, threshold: [0.1, 0.25, 0.5, 0.75, 0.9] }
    );
    for (const el of pageRefs.current.values()) observer.observe(el);
    return () => observer.disconnect();
  }, [pagesQuery.data]);

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

  async function acceptAllSuggested() {
    const eligible = (manifestQuery.data?.candidates ?? []).filter(
      (c) => c.state === "suggested" && c.exemption_code_id
    );
    if (eligible.length === 0) return;
    if (!window.confirm(`Approve all ${eligible.length} suggested candidate(s), each keeping its own AI-suggested exemption code?`)) {
      return;
    }
    setActionError(null);
    // The bulk endpoint applies one exemption_code_id to the whole batch it's given, and
    // candidates already carry different AI-suggested codes - grouping by code and firing
    // one bulk call per group (instead of one call for everything) is what keeps each
    // candidate's own code intact rather than overwriting all of them with a single code.
    const groups = new Map<string, string[]>();
    for (const c of eligible) {
      const codeId = c.exemption_code_id;
      if (!codeId) continue;
      const ids = groups.get(codeId) ?? [];
      ids.push(c.id);
      groups.set(codeId, ids);
    }
    const results = await Promise.all(
      Array.from(groups.entries()).map(([exemption_code_id, candidate_ids]) =>
        api.POST("/v1/documents/{doc_id}/candidates:bulk", {
          params: { path: { doc_id: docId } },
          body: { action: "approve", candidate_ids, exemption_code_id },
        })
      )
    );
    const firstError = results.find((r) => r.error)?.error;
    if (firstError) setActionError(problemMessage(firstError));
    refetchManifest();
  }

  async function handleSearchRedact() {
    if (!searchQuery.trim() || !searchCodeId) return;
    setActionError(null);
    setSearchStatus(null);
    setSearching(true);
    const { data, error } = await api.POST("/v1/documents/{doc_id}/search-redact", {
      params: { path: { doc_id: docId } },
      body: {
        query: searchQuery,
        is_pattern: false,
        scope: searchScope,
        page_no: searchScope === "page" ? activePageNo : undefined,
        exemption_code_id: searchCodeId,
      },
    });
    setSearching(false);
    if (error) {
      setActionError(problemMessage(error));
      return;
    }
    const count = data?.created.length ?? 0;
    setSearchStatus(count > 0 ? `Redacted ${count} match(es) for "${searchQuery}".` : `No matches found for "${searchQuery}".`);
    refetchManifest();
  }

  const createManualCandidate = useCallback(
    async (pageNo: number, bbox: BBoxT, exemptionCodeId: string) => {
      setActionError(null);
      const { error } = await api.POST("/v1/documents/{doc_id}/candidates", {
        params: { path: { doc_id: docId } },
        body: { page_no: pageNo, bbox, exemption_code_id: exemptionCodeId },
      });
      if (error) {
        setActionError(problemMessage(error));
        return;
      }
      refetchManifest();
    },
    [docId, refetchManifest]
  );

  const escalate = useCallback(
    async (candidate: Candidate) => {
      setActionError(null);
      const { error } = await api.POST("/v1/candidates/{candidate_id}:escalate", {
        params: { path: { candidate_id: candidate.id } },
        body: {},
      });
      if (error) {
        setActionError(problemMessage(error));
        return;
      }
      refetchManifest();
    },
    [refetchManifest]
  );

  async function saveJustification(candidate: Candidate, text: string) {
    await api.PATCH("/v1/candidates/{candidate_id}", {
      params: { path: { candidate_id: candidate.id } },
      body: { ai_justification: text },
    });
    refetchManifest();
  }

  const selectNextCandidate = useCallback(() => {
    const idx = allCandidatesSorted.findIndex((c) => c.id === selectedId);
    const next = allCandidatesSorted[idx + 1] ?? allCandidatesSorted[0];
    if (!next) return;
    setSelectedId(next.id);
    scrollToPage(next.page_no);
  }, [allCandidatesSorted, selectedId]);

  useEffect(() => {
    // Accessibility (WCAG 2.1.4, single-character key shortcuts): bare letter keys must
    // not fire while focus is on ANY text-entry or type-ahead-capable control, not just
    // textarea/input — a combobox trigger or a plain button can also consume typed
        // characters (e.g. Select's type-ahead). This is a partial mitigation, not full
    // 2.1.4 compliance (that needs a way to remap/disable the shortcuts entirely, which
    // isn't built) — flagged as a follow-up rather than silently claimed as done.
    function isTypingTarget(target: EventTarget | null): boolean {
      if (!(target instanceof HTMLElement)) return false;
      if (target instanceof HTMLTextAreaElement || target instanceof HTMLInputElement) return true;
      if (target.isContentEditable) return true;
      return target.closest('[role="combobox"], [data-slot="select-trigger"]') !== null;
    }
    function onKeyDown(e: KeyboardEvent) {
      if (isTypingTarget(e.target)) return;
      if (e.key.toLowerCase() === "c") setViewMode((v) => (v === "original" ? "preview" : "original"));
      if (!selected) return;
      if (e.key.toLowerCase() === "a") decide(selected, "approved");
      if (e.key.toLowerCase() === "r") decide(selected, "rejected");
      if (e.key.toLowerCase() === "n") selectNextCandidate();
      if (e.key.toLowerCase() === "e" && !selected.escalated_at) escalate(selected);
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [selected, decide, escalate, selectNextCandidate]);

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

  async function fetchArtifactBlob(artifactId: string): Promise<Blob | null> {
    // A plain <a href> won't carry the Authorization header the org-scoped download
    // endpoint requires — fetch it via the authenticated client instead.
    const { data, error } = await api.GET("/v1/exports/{export_id}/download", {
      params: { path: { export_id: artifactId } },
      parseAs: "blob",
    });
    if (error || !(data instanceof Blob)) {
      setActionError(problemMessage(error));
      return null;
    }
    return data;
  }

  async function viewArtifact(artifactId: string, filename: string) {
    // Deliberately renders in an in-page modal (below) via an <iframe>, not
    // window.open(blobUrl) in a new tab - verified directly (not just assumed) that a
    // blob: URL created in this document does NOT reliably navigate a *different*
    // window/tab to it, even one this page just opened itself; Chrome silently leaves it
    // at about:blank. An <iframe> in the same document that created the blob URL doesn't
    // have that problem at all, so it's not just a workaround, it's the more robust
    // option.
    const blob = await fetchArtifactBlob(artifactId);
    if (!blob) return;
    setPreviewArtifact({ url: URL.createObjectURL(blob), filename });
  }

  async function downloadArtifact(artifactId: string, filename: string) {
    const blob = await fetchArtifactBlob(artifactId);
    if (!blob) return;
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    link.click();
    URL.revokeObjectURL(url);
  }

  function closeArtifactPreview() {
    if (previewArtifact) URL.revokeObjectURL(previewArtifact.url);
    setPreviewArtifact(null);
  }

  async function handleExport() {
    // specs/07-ui-spec.md Design standards: "Every destructive/irreversible action
    // confirms with consequence text." Export burns redactions permanently, so a single
    // accidental click had no way back. A native confirm() is a real, keyboard- and
    // screen-reader-accessible modal (not a custom one that could introduce its own
    // focus-trap bugs).
    if (!window.confirm("Export burns these redactions permanently into the file — this cannot be undone. Continue?")) {
      return;
    }
    setActionError(null);
    const { error } = await api.POST("/v1/documents/{doc_id}/exports", {
      params: { path: { doc_id: docId } },
      body: { types: exportTypes },
    });
    if (error) {
      setActionError(problemMessage(error));
      return;
    }
    setRightTab("exports");
    queryClient.invalidateQueries({ queryKey: ["document", docId] });
    queryClient.invalidateQueries({ queryKey: ["exports", "doc", docId] });
  }

  if (docQuery.isLoading) {
    return (
      <AppShell variant="compact">
        <main id="main-content" role="status" className="p-8 text-sm text-neutral-500">
          Loading…
        </main>
      </AppShell>
    );
  }
  if (!docQuery.data) return null;
  const doc = docQuery.data;

  return (
    <AppShell variant="compact">
      <main id="main-content" className="flex h-full flex-1 flex-col overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b p-3">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <Link href="/documents" className="text-neutral-500 hover:underline">
              Documents
            </Link>
            <span className="text-neutral-400">/</span>
            <h1 className="font-medium">{doc.filename}</h1>
            <StatusPill status={doc.status} />
            <span className="text-xs text-neutral-500">manifest v{manifestQuery.data?.version}</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="flex items-center rounded-md border p-0.5 text-sm">
              <button
                onClick={() => setViewMode("original")}
                className={cn("rounded-sm px-2 py-1", viewMode === "original" ? "bg-muted font-medium" : "text-neutral-500")}
              >
                Original
              </button>
              <button
                onClick={() => setViewMode("preview")}
                className={cn("rounded-sm px-2 py-1", viewMode === "preview" ? "bg-muted font-medium" : "text-neutral-500")}
              >
                Redaction preview (C)
              </button>
            </div>
            <Button variant="outline" onClick={acceptAllSuggested}>
              Accept all suggested
            </Button>
            <Button onClick={handleCompleteReview} disabled={doc.status !== "ready_for_review" && doc.status !== "in_review"}>
              Complete review
            </Button>
          </div>
        </div>
        {actionError && (
          <p role="alert" className="border-b bg-red-50 p-2 text-sm text-red-600">
            {actionError}
          </p>
        )}
        {viewMode === "preview" && (
          <p role="status" className="border-b bg-blue-50 p-2 text-center text-xs text-blue-800 dark:bg-blue-950 dark:text-blue-300">
            Redaction preview — showing exactly what will be burned into the file if you export right now. Switch back to Original to keep editing.
          </p>
        )}

        <div className="flex flex-1 overflow-hidden">
          {/* Left rail: page list */}
          <aside className="w-40 shrink-0 overflow-y-auto border-r p-2">
            {pagesQuery.data?.map((p) => {
              const count = candidatesByPage.get(p.page_no)?.length ?? 0;
              const lowOcr = p.ocr_confidence != null && p.ocr_confidence < LOW_OCR_CONFIDENCE_THRESHOLD;
              return (
                <button
                  key={p.page_no}
                  onClick={() => scrollToPage(p.page_no)}
                  className={cn(
                    "mb-1 flex w-full items-center justify-between rounded px-2 py-1.5 text-sm",
                    p.page_no === activePageNo ? "bg-muted font-medium" : "hover:bg-muted/60"
                  )}
                >
                  <span>Page {p.page_no}</span>
                  <span className="flex items-center gap-1">
                    {lowOcr && (
                      <Badge variant="destructive" aria-label="Low OCR quality — review manually">
                        OCR
                      </Badge>
                    )}
                    {count > 0 && <Badge variant="secondary">{count}</Badge>}
                  </span>
                </button>
              );
            })}
          </aside>

          {/* Center: continuous-scroll viewer */}
          <section ref={scrollContainerRef} className="flex-1 overflow-auto bg-neutral-100 p-4 dark:bg-neutral-950">
            <div className="flex flex-col gap-6">
              {pagesQuery.data?.map((p) => (
                <PageView
                  key={p.page_no}
                  docId={docId}
                  page={p}
                  candidates={candidatesByPage.get(p.page_no) ?? []}
                  viewMode={viewMode}
                  selectedId={selectedId}
                  codes={codesQuery.data}
                  onSelectCandidate={(id, pageNo) => {
                    setSelectedId(id);
                    setActivePageNo(pageNo);
                    setRightTab("review");
                  }}
                  onCreateManual={createManualCandidate}
                  registerRef={registerPageRef}
                />
              ))}
            </div>
          </section>

          {/* Right panel */}
          <aside className="w-96 shrink-0 overflow-y-auto border-l p-4">
            <Tabs value={rightTab} onValueChange={(v) => setRightTab(v as "review" | "exports")}>
              <TabsList>
                <TabsTrigger value="review">Review</TabsTrigger>
                <TabsTrigger value="exports">
                  Exports{exportsQuery.data?.length ? ` (${exportsQuery.data.length})` : ""}
                </TabsTrigger>
              </TabsList>

              <TabsPanel value="review">
                {selected ? (
                  <div className="flex flex-col gap-3 pt-3">
                    <div>
                      <p className="text-xs text-neutral-500">Extracted text</p>
                      <p className="rounded bg-neutral-100 p-2 font-mono text-sm dark:bg-neutral-900">{selected.display_text}</p>
                    </div>
                    <div className="flex items-center gap-2">
                      <Badge variant="outline">{selected.confidence}</Badge>
                      <Badge variant="outline">{selected.origin}</Badge>
                      <Badge variant="outline">{selected.state}</Badge>
                    </div>
                    <div>
                      <Label htmlFor="exemption-code-select" className="mb-1 text-xs text-neutral-500">
                        Exemption code
                      </Label>
                      <Select
                        value={selected.exemption_code_id ?? undefined}
                        onValueChange={(v) => v && updateCode(selected, v)}
                      >
                        <SelectTrigger id="exemption-code-select">
                          {/* Passing children explicitly (rather than relying on SelectValue to
                              find and echo the matching SelectItem's label itself) - Radix only
                              registers item labels once SelectContent has mounted, so on first
                              render (before the dropdown is ever opened) it fell back to
                              rendering the raw exemption_code_id string instead of "code — label". */}
                          <SelectValue placeholder="Choose a code…">{selectedCodeLabel}</SelectValue>
                        </SelectTrigger>
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
                        <Label htmlFor="ai-justification" className="mb-1 text-xs text-neutral-500">
                          AI justification (editable)
                        </Label>
                        <Textarea
                          id="ai-justification"
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
                      {selected.escalated_at ? (
                        <Badge variant="destructive" title={selected.escalated_note ?? undefined}>
                          Escalated
                        </Badge>
                      ) : (
                        <Button variant="ghost" onClick={() => escalate(selected)}>
                          Escalate (E)
                        </Button>
                      )}
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
                  <p className="pt-3 text-sm text-neutral-500">
                    Select a highlighted region to review it, or drag directly on a page to mark new text for
                    redaction. {allCandidatesSorted.length} candidate(s) in this document.
                  </p>
                )}

                <Separator className="my-4" />

                {/* AI suggestions come from detection rules matching known entity types/patterns
                    - this covers anything a reviewer spots that the AI missed (a name, a
                    specific phrase) by searching the document's real extracted text for exact
                    occurrences and creating already-approved candidates from each match, with
                    the same exemption-code tagging every other candidate requires. Dragging a
                    box directly on the page (above) covers the same need for a single spot
                    instance; this covers every occurrence at once. */}
                <div className="flex flex-col gap-2">
                  <p className="text-xs text-neutral-500">Find &amp; redact every occurrence of some text</p>
                  <Input
                    placeholder="Exact text to find and redact…"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                  />
                  <Select value={searchScope} onValueChange={(v) => v && setSearchScope(v as "page" | "document")}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="document">Whole document</SelectItem>
                      <SelectItem value="page">This page only</SelectItem>
                    </SelectContent>
                  </Select>
                  <Select value={searchCodeId} onValueChange={(v) => v && setSearchCodeId(v)}>
                    <SelectTrigger>
                      <SelectValue placeholder="Choose a code…">
                        {searchCodeId ? codesQuery.data?.find((c) => c.id === searchCodeId)?.label : undefined}
                      </SelectValue>
                    </SelectTrigger>
                    <SelectContent>
                      {codesQuery.data?.map((code) => (
                        <SelectItem key={code.id} value={code.id}>
                          {code.code} — {code.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <Button size="sm" variant="outline" onClick={handleSearchRedact} disabled={!searchQuery.trim() || !searchCodeId || searching}>
                    {searching ? "Searching…" : "Find & redact all matches"}
                  </Button>
                  {searchStatus && <p role="status" aria-live="polite" className="text-xs text-neutral-500">{searchStatus}</p>}
                </div>
              </TabsPanel>

              <TabsPanel value="exports">
                <div className="flex flex-col gap-3 pt-3">
                  <p className="text-xs text-neutral-500">
                    Every export ever generated for this document — always available to re-view or re-download, not
                    just the one you just ran.
                  </p>
                  {exportsQuery.isLoading ? (
                    <p className="text-sm text-neutral-500">Loading…</p>
                  ) : exportsQuery.data?.length === 0 ? (
                    <p className="text-sm text-neutral-500">No exports yet — use the Export panel below once review is complete.</p>
                  ) : (
                    <ul className="flex flex-col divide-y">
                      {exportsQuery.data?.map((artifact) => {
                        const filename = exportFilename(doc.filename, artifact.type);
                        return (
                          <li key={artifact.id} className="flex flex-col gap-1.5 py-2.5 text-sm">
                            <div className="flex items-center justify-between">
                              <span className="font-medium">{artifact.type.replace(/_/g, " ")}</span>
                              <Badge variant={artifact.integrity_check.passed ? "outline" : "destructive"}>
                                {artifact.integrity_check.passed ? "integrity ✓" : "integrity ✗ FAILED"}
                              </Badge>
                            </div>
                            <span className="text-xs text-neutral-500">{new Date(artifact.created_at).toLocaleString()}</span>
                            <div className="flex gap-2">
                              <Button size="sm" variant="outline" onClick={() => viewArtifact(artifact.id, filename)}>
                                <ExternalLink className="size-3.5" /> View
                              </Button>
                              <Button size="sm" variant="outline" onClick={() => downloadArtifact(artifact.id, filename)}>
                                <Download className="size-3.5" /> Download
                              </Button>
                            </div>
                          </li>
                        );
                      })}
                    </ul>
                  )}
                </div>
              </TabsPanel>
            </Tabs>
          </aside>
        </div>

        <div className="flex items-center justify-between border-t p-3 text-sm">
          <span aria-live="polite" className="text-neutral-500">
            {lowConfidenceUnresolved > 0
              ? `${lowConfidenceUnresolved} low-confidence candidate(s) unresolved`
              : "All low-confidence candidates resolved"}
            {" · "}Shortcuts: A approve · R reject · E escalate · N next · C compare
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
      </main>

      <Dialog.Root open={!!previewArtifact} onOpenChange={(open) => !open && closeArtifactPreview()}>
        <Dialog.Portal>
          <Dialog.Backdrop className="fixed inset-0 z-50 bg-black/50" />
          <Dialog.Popup className="fixed inset-6 z-50 flex flex-col overflow-hidden rounded-lg border bg-background shadow-2xl">
            <div className="flex items-center justify-between border-b p-3">
              <Dialog.Title className="text-sm font-medium">{previewArtifact?.filename}</Dialog.Title>
              <Dialog.Close
                render={
                  <button aria-label="Close preview" className="text-neutral-400 hover:text-neutral-600">
                    <X className="size-5" />
                  </button>
                }
              />
            </div>
            {previewArtifact && (
              <iframe title={previewArtifact.filename} src={previewArtifact.url} className="flex-1 bg-white" />
            )}
          </Dialog.Popup>
        </Dialog.Portal>
      </Dialog.Root>
    </AppShell>
  );
}
