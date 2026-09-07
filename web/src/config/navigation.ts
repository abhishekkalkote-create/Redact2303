import type { LucideIcon } from "lucide-react";
import { BookText, CreditCard, FileText, LayoutDashboard, ShieldCheck, SlidersHorizontal } from "lucide-react";

export interface NavDestination {
  label: string;
  href: string;
  icon: LucideIcon;
  keywords?: string;
}

/**
 * Single source of truth for cross-page navigation - both the sidebar (AppShell) and
 * the ⌘K command palette read from this list, so adding a destination never means
 * updating two places that can drift out of sync.
 */
export const NAV_DESTINATIONS: NavDestination[] = [
  { label: "Dashboard", href: "/dashboard", icon: LayoutDashboard },
  { label: "Documents", href: "/documents", icon: FileText, keywords: "upload review" },
  { label: "Rules & Policies", href: "/rules", icon: SlidersHorizontal, keywords: "exemption packs" },
  { label: "Security", href: "/security", icon: ShieldCheck },
  { label: "Docs", href: "/docs", icon: BookText, keywords: "api reference help" },
  { label: "Pricing", href: "/pricing", icon: CreditCard, keywords: "plan billing" },
];
