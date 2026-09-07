import { statusMeta } from "@/lib/status";
import { cn } from "@/lib/utils";

/** Renders a document/candidate status via `lib/status.ts`'s shared, action-button-distinct styling. */
export function StatusPill({ status, className }: { status: string; className?: string }) {
  const meta = statusMeta(status);
  return (
    <span
      className={cn(
        "inline-flex w-fit shrink-0 items-center rounded-full border px-2 py-0.5 text-xs font-medium whitespace-nowrap",
        meta.className,
        className
      )}
    >
      {meta.label}
    </span>
  );
}
