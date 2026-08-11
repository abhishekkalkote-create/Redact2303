"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { MarketingHome } from "@/components/marketing/marketing-home";
import { getToken } from "@/lib/auth";
import { api } from "@/lib/api-client";

/**
 * specs/07-ui-spec.md § 11: the marketing homepage lives at the same root path this app
 * already used for its logged-in-vs-anonymous redirect. An anonymous visitor sees the
 * marketing page directly; a logged-in one is bounced to onboarding/dashboard before it
 * ever renders, same as before this page had marketing content at all.
 */
export default function Home() {
  const router = useRouter();
  const [checkingSession, setCheckingSession] = useState(true);

  useEffect(() => {
    if (!getToken()) {
      setCheckingSession(false);
      return;
    }
    api.GET("/v1/orgs/current", {}).then(({ error }) => {
      router.replace(error ? "/onboarding" : "/dashboard");
    });
  }, [router]);

  if (checkingSession) {
    return <main className="flex flex-1 items-center justify-center text-sm text-neutral-500">Loading…</main>;
  }

  return <MarketingHome />;
}
