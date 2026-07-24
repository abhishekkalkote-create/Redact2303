"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { getToken } from "@/lib/auth";
import { api } from "@/lib/api-client";

export default function Home() {
  const router = useRouter();

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    api.GET("/v1/orgs/current", {}).then(({ error }) => {
      router.replace(error ? "/onboarding" : "/dashboard");
    });
  }, [router]);

  return <main className="flex flex-1 items-center justify-center text-sm text-neutral-500">Loading…</main>;
}
