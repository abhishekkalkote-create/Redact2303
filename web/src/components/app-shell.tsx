"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Menu } from "@base-ui/react/menu";
import { Tooltip } from "@base-ui/react/tooltip";
import { LogOut, Search, ShieldCheck } from "lucide-react";
import { NAV_DESTINATIONS } from "@/config/navigation";
import { api } from "@/lib/api-client";
import { clearToken } from "@/lib/auth";
import { cn } from "@/lib/utils";

function openCommandPalette() {
  // CommandPalette (mounted once in the root layout) listens for this exact chord on
  // `window` - dispatching it here means the sidebar's search button and the real ⌘K
  // shortcut both go through one code path instead of duplicating the open logic.
  window.dispatchEvent(new KeyboardEvent("keydown", { key: "k", metaKey: true, ctrlKey: true }));
}

function SidebarLink({ href, label, icon: Icon, compact, active }: {
  href: string;
  label: string;
  icon: (typeof NAV_DESTINATIONS)[number]["icon"];
  compact: boolean;
  active: boolean;
}) {
  const link = (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      className={cn(
        "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
        compact && "justify-center px-2",
        active
          ? "bg-sidebar-accent text-sidebar-accent-foreground"
          : "text-sidebar-foreground/70 hover:bg-sidebar-accent/60 hover:text-sidebar-foreground"
      )}
    >
      <Icon className="size-4 shrink-0" aria-hidden />
      {!compact && <span className="truncate">{label}</span>}
    </Link>
  );

  if (!compact) return link;

  return (
    <Tooltip.Root>
      <Tooltip.Trigger render={link} />
      <Tooltip.Portal>
        <Tooltip.Positioner side="right" sideOffset={8}>
          <Tooltip.Popup className="rounded-md bg-neutral-900 px-2 py-1 text-xs text-white shadow-md dark:bg-neutral-100 dark:text-neutral-900">
            {label}
          </Tooltip.Popup>
        </Tooltip.Positioner>
      </Tooltip.Portal>
    </Tooltip.Root>
  );
}

function OrgMenu({ compact }: { compact: boolean }) {
  const router = useRouter();
  const orgQuery = useQuery({
    queryKey: ["org"],
    queryFn: async () => {
      const { data, error } = await api.GET("/v1/orgs/current", {});
      if (error) throw error;
      return data;
    },
    retry: false,
  });

  function handleLogout() {
    clearToken();
    router.push("/login");
  }

  const trigger = (
    <button
      type="button"
      className={cn(
        "flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm text-sidebar-foreground/80 hover:bg-sidebar-accent/60 hover:text-sidebar-foreground",
        compact && "justify-center px-2"
      )}
    >
      <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-sidebar-primary text-xs font-semibold text-sidebar-primary-foreground">
        {(orgQuery.data?.name ?? "?").slice(0, 1).toUpperCase()}
      </span>
      {!compact && <span className="truncate">{orgQuery.data?.name ?? "Loading…"}</span>}
    </button>
  );

  return (
    <Menu.Root>
      <Menu.Trigger render={trigger} />
      <Menu.Portal>
        <Menu.Positioner side="top" align="start" sideOffset={6}>
          <Menu.Popup className="min-w-48 rounded-lg border bg-popover p-1 text-popover-foreground shadow-lg">
            {orgQuery.data && (
              <div className="px-2 py-1.5 text-xs text-muted-foreground">
                {orgQuery.data.name} · {orgQuery.data.plan}
              </div>
            )}
            <Menu.Item
              onClick={handleLogout}
              className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm outline-none hover:bg-muted data-[highlighted]:bg-muted"
            >
              <LogOut className="size-4" aria-hidden /> Log out
            </Menu.Item>
          </Menu.Popup>
        </Menu.Positioner>
      </Menu.Portal>
    </Menu.Root>
  );
}

/**
 * Persistent left-nav application chrome - specs/07-ui-spec.md screen 2 calls for a
 * "Left nav: Dashboard, Documents, Requests, Rules & Policies, Audit, Usage & Billing,
 * Settings" on every authenticated screen, but no shared shell existed: every page
 * before this wired its own ad hoc back-link (or none at all), so there was never a
 * reliable way back to the dashboard from, say, Documents. Every authenticated page
 * should render its content through this instead of a bare `<main>`.
 *
 * `variant="compact"` is for the review workspace, which is already a dense 3-pane
 * layout (page thumbnails · viewer · candidate panel) - a labeled sidebar on top of
 * that would eat width the workspace needs, so compact collapses to an icon-only rail
 * (labels still reachable via tooltip) while keeping every destination one click away.
 */
export function AppShell({ children, variant = "full" }: { children: ReactNode; variant?: "full" | "compact" }) {
  const pathname = usePathname();
  const compact = variant === "compact";

  return (
    <div className="flex h-screen w-full overflow-hidden bg-background">
      <Tooltip.Provider delay={200}>
      <aside
        className={cn(
          "flex shrink-0 flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground",
          compact ? "w-14 items-center" : "w-56"
        )}
      >
        <Link
          href="/dashboard"
          className={cn(
            "flex items-center gap-2 px-4 py-4 text-sm font-semibold text-sidebar-foreground",
            compact && "justify-center px-0"
          )}
          aria-label="RedactProof home"
        >
          <ShieldCheck className="size-5 shrink-0 text-sidebar-primary" aria-hidden />
          {!compact && <span>RedactProof</span>}
        </Link>

        <nav className={cn("flex flex-1 flex-col gap-0.5 overflow-y-auto px-2", compact && "items-center px-2")}>
          {NAV_DESTINATIONS.map((d) => (
            <SidebarLink
              key={d.href}
              href={d.href}
              label={d.label}
              icon={d.icon}
              compact={compact}
              active={pathname === d.href || pathname?.startsWith(`${d.href}/`)}
            />
          ))}
        </nav>

        <div className={cn("flex flex-col gap-0.5 border-t border-sidebar-border p-2", compact && "items-center")}>
          {compact ? (
            <Tooltip.Root>
              <Tooltip.Trigger
                render={
                  <button
                    type="button"
                    onClick={openCommandPalette}
                    className="flex items-center justify-center rounded-md p-2 text-sidebar-foreground/70 hover:bg-sidebar-accent/60 hover:text-sidebar-foreground"
                    aria-label="Search (⌘K)"
                  >
                    <Search className="size-4" aria-hidden />
                  </button>
                }
              />
              <Tooltip.Portal>
                <Tooltip.Positioner side="right" sideOffset={8}>
                  <Tooltip.Popup className="rounded-md bg-neutral-900 px-2 py-1 text-xs text-white shadow-md dark:bg-neutral-100 dark:text-neutral-900">
                    Search (⌘K)
                  </Tooltip.Popup>
                </Tooltip.Positioner>
              </Tooltip.Portal>
            </Tooltip.Root>
          ) : (
            <button
              type="button"
              onClick={openCommandPalette}
              className="flex items-center gap-3 rounded-md px-3 py-2 text-sm text-sidebar-foreground/70 hover:bg-sidebar-accent/60 hover:text-sidebar-foreground"
            >
              <Search className="size-4 shrink-0" aria-hidden />
              <span className="flex flex-1 items-center justify-between">
                Search <kbd className="rounded border border-sidebar-border px-1 text-[10px]">⌘K</kbd>
              </span>
            </button>
          )}
          <OrgMenu compact={compact} />
        </div>
      </aside>
      </Tooltip.Provider>

      <div className={cn("flex flex-1 flex-col", compact ? "overflow-hidden" : "overflow-y-auto")}>{children}</div>
    </div>
  );
}
