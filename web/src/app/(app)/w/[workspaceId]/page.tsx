"use client";

import { BarChart3, CalendarClock, Inbox, Sparkles } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";

import { PageHeader } from "@/components/page-header";
import { EmptyState, ErrorState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useBrandKit, useWorkspace } from "@/lib/api/hooks";

export default function DashboardPage() {
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const ws = useWorkspace(workspaceId);
  const kit = useBrandKit(workspaceId);

  if (ws.error) return <ErrorState error={ws.error} onRetry={() => ws.refetch()} />;

  const brandIncomplete = kit.data && (!kit.data.voice_tone || !kit.data.primary_color);

  return (
    <>
      {ws.isLoading ? (
        <Skeleton className="mb-8 h-10 w-64" />
      ) : (
        <PageHeader
          title={ws.data!.name}
          description="Everything waiting on you, and what’s going out next."
        />
      )}

      {brandIncomplete && (
        <div className="mb-8 flex flex-wrap items-center gap-4 rounded-lg border border-marigold/40 bg-marigold-soft px-5 py-4">
          <p className="flex-1 text-sm">
            <span className="font-medium">Finish your brand kit.</span> The agent writes better when
            it knows your voice and colours.
          </p>
          <Button asChild size="sm" variant="outline">
            <Link href={`/w/${workspaceId}/brand`}>Open brand kit</Link>
          </Button>
        </div>
      )}

      <div className="grid gap-x-10 gap-y-10 lg:grid-cols-2">
        <Section title="Waiting on you">
          <EmptyState icon={Inbox} title="Nothing to review">
            When the agent drafts posts, emails or posters, they land here for your approval.
            Nothing is published without it.
          </EmptyState>
        </Section>
        <Section title="Going out next">
          <EmptyState icon={CalendarClock} title="Nothing scheduled">
            Approved content you schedule will show up here with its date and channel.
          </EmptyState>
        </Section>
        <Section title="Recent agent runs">
          <EmptyState icon={Sparkles} title="No runs yet">
            Each conversation with the agent is saved here with every step it took.
          </EmptyState>
        </Section>
        <Section title="Performance">
          <EmptyState icon={BarChart3} title="No metrics yet">
            Metrics appear once a connected Instagram or LinkedIn account has published posts. We
            only show numbers pulled from the platforms.
          </EmptyState>
        </Section>
      </div>
    </>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="border-t pt-5">
      <h2 className="mb-4 text-base font-semibold">{title}</h2>
      {children}
    </section>
  );
}
