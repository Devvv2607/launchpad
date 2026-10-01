"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { Logo } from "@/components/logo";
import { ErrorState } from "@/components/states";
import { useWorkspaces } from "@/lib/api/hooks";

import { LAST_WS_KEY } from "@/lib/workspace";

/** Entry point: go to the last-used workspace, or onboarding if the user has none. */
export default function Home() {
  const router = useRouter();
  const workspaces = useWorkspaces();

  useEffect(() => {
    if (!workspaces.data) return;
    if (workspaces.data.length === 0) {
      router.replace("/onboarding");
      return;
    }
    let last: string | null = null;
    try {
      last = localStorage.getItem(LAST_WS_KEY);
    } catch {}
    const target = workspaces.data.find((w) => w.id === last) ?? workspaces.data[0];
    router.replace(`/w/${target.id}`);
  }, [workspaces.data, router]);

  return (
    <div className="grid min-h-dvh place-items-center p-6">
      {workspaces.error ? (
        <ErrorState
          className="max-w-md"
          error={workspaces.error}
          onRetry={() => workspaces.refetch()}
        />
      ) : (
        <Logo className="animate-pulse text-muted-foreground" />
      )}
    </div>
  );
}
