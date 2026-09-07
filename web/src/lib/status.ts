/**
 * Shared document-status presentation, used by the dashboard, documents grid, and
 * review workspace so a status always looks the same everywhere.
 *
 * Deliberately never reuses Button's solid/filled look (bg-primary etc.) - a status is
 * information, never an action, and a status pill that looks as visually "loud" as a
 * real action button (e.g. "Complete review") reads as a second, competing button. Every
 * variant here is a quiet tint + border instead.
 */
export interface StatusMeta {
  label: string;
  className: string;
}

const STATUS_META: Record<string, StatusMeta> = {
  new: { label: "New", className: "bg-neutral-100 text-neutral-600 border-neutral-200 dark:bg-neutral-800 dark:text-neutral-300 dark:border-neutral-700" },
  processing: { label: "Processing", className: "bg-blue-50 text-blue-700 border-blue-200 dark:bg-blue-950 dark:text-blue-300 dark:border-blue-900" },
  ready_for_review: { label: "Ready for review", className: "bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-950 dark:text-amber-300 dark:border-amber-900" },
  in_review: { label: "In review", className: "bg-blue-50 text-blue-700 border-blue-200 dark:bg-blue-950 dark:text-blue-300 dark:border-blue-900" },
  awaiting_approval: { label: "Awaiting approval", className: "bg-violet-50 text-violet-700 border-violet-200 dark:bg-violet-950 dark:text-violet-300 dark:border-violet-900" },
  review_complete: { label: "Review complete", className: "bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-950 dark:text-emerald-300 dark:border-emerald-900" },
  exported: { label: "Exported", className: "bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-950 dark:text-emerald-300 dark:border-emerald-900" },
  error: { label: "Error", className: "bg-red-50 text-red-700 border-red-200 dark:bg-red-950 dark:text-red-300 dark:border-red-900" },
};

export function statusMeta(status: string): StatusMeta {
  return STATUS_META[status] ?? { label: status, className: "bg-neutral-100 text-neutral-600 border-neutral-200 dark:bg-neutral-800 dark:text-neutral-300 dark:border-neutral-700" };
}
