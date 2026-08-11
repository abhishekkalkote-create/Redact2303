import type { ReactNode } from "react";
import Link from "next/link";
import { buttonVariants } from "@/components/ui/button";

const NAV_LINKS = [
  { href: "/pricing", label: "Pricing" },
  { href: "/security", label: "Security & Trust" },
  { href: "/docs", label: "Docs" },
];

/**
 * specs/07-ui-spec.md § 11 "Marketing site (separate, static)". Built as a set of
 * unauthenticated routes inside this same Next.js app rather than a genuinely separate
 * static project — see the Phase 5 slice-9 scoping note. Shared, unauthenticated chrome
 * for /, /pricing, /security, /docs; the authenticated app has its own nav (SideNav)
 * and never renders this.
 */
export function MarketingShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-full flex-1 flex-col">
      <header className="border-b border-neutral-200">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-4">
          <Link href="/" className="text-sm font-semibold tracking-tight">
            RedactProof
          </Link>
          <nav className="flex items-center gap-6">
            {NAV_LINKS.map((link) => (
              <Link key={link.href} href={link.href} className="text-sm text-neutral-600 hover:text-neutral-900">
                {link.label}
              </Link>
            ))}
            <Link href="/login" className={buttonVariants({ variant: "outline", size: "sm" })}>
              Log in
            </Link>
          </nav>
        </div>
      </header>
      <main className="flex-1">{children}</main>
      <footer className="border-t border-neutral-200">
        <div className="mx-auto flex max-w-5xl flex-col gap-2 px-6 py-8 text-xs text-neutral-500">
          <p>&copy; {new Date().getFullYear()} RedactProof. AI-assisted, human-verified document redaction.</p>
          <p>Built for public-records and FOIA teams at state and local agencies. Hosted in the US.</p>
        </div>
      </footer>
    </div>
  );
}
