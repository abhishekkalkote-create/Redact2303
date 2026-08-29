"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Dialog } from "@base-ui/react/dialog";

interface Destination {
  label: string;
  href: string;
  keywords?: string;
}

// No shared top-nav exists in this app (each page is standalone) - this is the first
// cross-page navigation surface, so the destination list lives here rather than in a
// nav config nobody else reads yet.
const DESTINATIONS: Destination[] = [
  { label: "Dashboard", href: "/dashboard" },
  { label: "Documents", href: "/documents", keywords: "upload review" },
  { label: "Rules", href: "/rules", keywords: "exemption packs" },
  { label: "Security", href: "/security" },
  { label: "Docs", href: "/docs", keywords: "api reference help" },
  { label: "Pricing", href: "/pricing", keywords: "plan billing" },
];

export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const router = useRouter();

  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return DESTINATIONS;
    return DESTINATIONS.filter(
      (d) => d.label.toLowerCase().includes(q) || d.keywords?.toLowerCase().includes(q)
    );
  }, [query]);

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((prev) => !prev);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  useEffect(() => {
    if (open) {
      setQuery("");
      setActiveIndex(0);
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [open]);

  useEffect(() => {
    setActiveIndex(0);
  }, [query]);

  function go(href: string) {
    setOpen(false);
    router.push(href);
  }

  function onInputKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIndex((i) => Math.min(i + 1, results.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const target = results[activeIndex];
      if (target) go(target.href);
    }
  }

  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Portal>
        <Dialog.Backdrop className="fixed inset-0 z-50 bg-black/40" />
        <Dialog.Popup className="fixed top-[20%] left-1/2 z-50 w-full max-w-md -translate-x-1/2 overflow-hidden rounded-lg border bg-white shadow-xl dark:bg-neutral-900">
          <Dialog.Title className="sr-only">Jump to</Dialog.Title>
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={onInputKeyDown}
            placeholder="Jump to…"
            aria-label="Jump to a page"
            aria-activedescendant={results[activeIndex] ? `cmdk-option-${activeIndex}` : undefined}
            role="combobox"
            aria-expanded
            aria-controls="cmdk-listbox"
            className="w-full border-b bg-transparent px-4 py-3 text-sm outline-none"
          />
          <ul id="cmdk-listbox" role="listbox" className="max-h-72 overflow-y-auto p-1">
            {results.length === 0 && (
              <li className="px-3 py-2 text-sm text-neutral-500">No matches</li>
            )}
            {results.map((d, i) => (
              <li key={d.href} id={`cmdk-option-${i}`} role="option" aria-selected={i === activeIndex}>
                <button
                  onClick={() => go(d.href)}
                  onMouseEnter={() => setActiveIndex(i)}
                  className={`block w-full rounded-md px-3 py-2 text-left text-sm ${
                    i === activeIndex ? "bg-neutral-200 dark:bg-neutral-800" : "hover:bg-neutral-100 dark:hover:bg-neutral-800"
                  }`}
                >
                  {d.label}
                </button>
              </li>
            ))}
          </ul>
        </Dialog.Popup>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
