"use client";

import { Activity, AlertTriangle } from "lucide-react";
import { useParams } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { PageHeader } from "@/components/page-header";
import { EmptyState, ErrorState, ListSkeleton } from "@/components/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { Schemas } from "@/lib/api/client";
import { useAISettings, useSaveAISettings, useUsage } from "@/lib/api/hooks";

const PURPOSES: { key: Schemas["Purpose"]; label: string; help: string }[] = [
  { key: "writing", label: "Writing", help: "Drafting posts, emails and voice profiles" },
  { key: "critique", label: "Review", help: "Scoring and revising drafts, hashtags" },
  { key: "planning", label: "Planning", help: "Campaign calendars and the agent's plans" },
  { key: "embedding", label: "Brand knowledge", help: "Indexing and searching brand documents" },
];

const usd = (n: number) => (n < 0.01 && n > 0 ? `$${n.toFixed(4)}` : `$${n.toFixed(2)}`);
const num = (n: number) => n.toLocaleString("en-IN");

export default function AISettingsPage() {
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const settings = useAISettings(workspaceId);
  return (
    <>
      <PageHeader
        title="AI settings"
        description="Which models do the work, what it costs, and a daily budget so nothing runs away."
      />
      {settings.error ? (
        <ErrorState error={settings.error} onRetry={() => settings.refetch()} />
      ) : !settings.data ? (
        <ListSkeleton rows={5} />
      ) : (
        <div className="max-w-4xl space-y-12">
          <Routing workspaceId={workspaceId} data={settings.data} />
          <Usage workspaceId={workspaceId} />
        </div>
      )}
    </>
  );
}

function Routing({ workspaceId, data }: { workspaceId: string; data: Schemas["AISettingsOut"] }) {
  const save = useSaveAISettings(workspaceId);
  const [routes, setRoutes] = useState<Record<string, Schemas["PurposeRoute"] | null>>(() => ({
    ...data.routes,
  }));
  const [cap, setCap] = useState(
    data.daily_spend_cap_usd == null ? "" : String(data.daily_spend_cap_usd),
  );

  function submit() {
    const clean = Object.fromEntries(Object.entries(routes).filter(([, r]) => r)) as Record<
      string,
      Schemas["PurposeRoute"]
    >;
    save.mutate(
      { routes: clean, daily_spend_cap_usd: cap === "" ? null : Number(cap) },
      { onSuccess: () => toast.success("AI settings saved") },
    );
  }

  return (
    <section className="space-y-5">
      <div>
        <h2 className="text-lg font-semibold">Models</h2>
        <p className="text-sm text-muted-foreground">
          Defaults come from the server&apos;s environment. Override per task with any provider that
          has an API key (
          {data.configured_providers.length
            ? data.configured_providers.join(", ")
            : "none configured"}
          ). There is no automatic fallback: if a model fails, you&apos;ll see why.
        </p>
      </div>
      <ul className="divide-y rounded-lg border bg-card">
        {PURPOSES.map((p) => {
          const eff = data.effective[p.key];
          const options = data.catalog.filter((m) =>
            p.key === "embedding" ? m.embedding : !m.embedding,
          );
          const route = routes[p.key];
          const value = route ? `${route.provider}|${route.model}` : "default";
          return (
            <li
              key={p.key}
              className="grid gap-3 p-4 sm:grid-cols-[1fr_minmax(0,18rem)] sm:items-center"
            >
              <div className="min-w-0">
                <p className="font-medium">{p.label}</p>
                <p className="text-sm text-muted-foreground">{p.help}</p>
                {eff.error ? (
                  <p className="mt-1 flex items-start gap-1 text-sm text-rose">
                    <AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden /> {eff.error}
                  </p>
                ) : (
                  <p className="mt-1 text-xs text-muted-foreground">
                    Using{" "}
                    <code>
                      {eff.provider}:{eff.model}
                    </code>{" "}
                    ({eff.source === "workspace" ? "this workspace" : "server default"})
                  </p>
                )}
              </div>
              <Select
                value={value}
                onValueChange={(v) => {
                  if (v === "default") setRoutes((r) => ({ ...r, [p.key]: null }));
                  else {
                    const [provider, model] = v.split("|");
                    setRoutes((r) => ({
                      ...r,
                      [p.key]: { provider: provider as Schemas["PurposeRoute"]["provider"], model },
                    }));
                  }
                }}
              >
                <SelectTrigger className="w-full" aria-label={`${p.label} model`}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="default">Server default</SelectItem>
                  {options.map((m) => (
                    <SelectItem key={`${m.provider}|${m.model}`} value={`${m.provider}|${m.model}`}>
                      {m.provider}: {m.model}
                      <span className="ml-2 text-xs text-muted-foreground">
                        {m.input_per_m == null
                          ? "price unknown"
                          : `$${m.input_per_m}/$${m.output_per_m} per 1M`}
                        {m.price_official === false && " (unverified)"}
                      </span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </li>
          );
        })}
      </ul>

      <div className="flex flex-wrap items-end gap-4">
        <div className="space-y-1.5">
          <label htmlFor="cap" className="text-sm font-medium">
            Daily spend cap (USD)
          </label>
          <Input
            id="cap"
            type="number"
            min={0}
            max={1000}
            step="0.5"
            className="w-36"
            placeholder={String(data.default_daily_cap_usd)}
            value={cap}
            onChange={(e) => setCap(e.target.value)}
          />
          <p className="text-xs text-muted-foreground">
            Empty uses the server default (${data.default_daily_cap_usd.toFixed(2)}). AI calls stop
            for the day once it&apos;s reached.
          </p>
        </div>
        <Button onClick={submit} disabled={save.isPending}>
          {save.isPending ? "Saving…" : "Save AI settings"}
        </Button>
      </div>
      {save.error && <ErrorState error={save.error} />}
    </section>
  );
}

function Usage({ workspaceId }: { workspaceId: string }) {
  const usage = useUsage(workspaceId);
  if (usage.error) return <ErrorState error={usage.error} onRetry={() => usage.refetch()} />;
  if (!usage.data) return <ListSkeleton rows={3} />;
  const u = usage.data;
  const capUsed =
    u.daily_cap_usd > 0 ? Math.min(100, (u.today_spent_usd / u.daily_cap_usd) * 100) : 100;
  return (
    <section className="space-y-5">
      <div>
        <h2 className="text-lg font-semibold">Usage this month</h2>
        <p className="text-sm text-muted-foreground">
          From every AI call this workspace made in {u.month} ({u.timezone}). Costs are estimates
          from published prices.
        </p>
      </div>
      <div className="rounded-lg border bg-card p-4">
        <div className="flex items-baseline justify-between text-sm">
          <span className="font-medium">Today</span>
          <span className="tabular-nums">
            {usd(u.today_spent_usd)} of {usd(u.daily_cap_usd)}
          </span>
        </div>
        <div
          className="mt-2 h-2 overflow-hidden rounded-full bg-muted"
          role="img"
          aria-label={`${Math.round(capUsed)}% of today's cap used`}
        >
          <div
            className={
              capUsed >= 90
                ? "h-full bg-rose"
                : capUsed >= 60
                  ? "h-full bg-marigold"
                  : "h-full bg-leaf"
            }
            style={{ width: `${capUsed}%` }}
          />
        </div>
      </div>
      {u.totals.calls === 0 ? (
        <EmptyState icon={Activity} title="No AI calls this month">
          Usage appears here as soon as you generate content or index brand documents.
        </EmptyState>
      ) : (
        <>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-4">
            {[
              ["Calls", num(u.totals.calls)],
              ["Failed", num(u.totals.errors)],
              ["Tokens", `${num(u.totals.tokens_in + u.totals.tokens_out)}`],
              ["Estimated cost", usd(u.totals.cost_usd)],
            ].map(([k, v]) => (
              <div key={k}>
                <dt className="text-xs text-muted-foreground">{k}</dt>
                <dd className="font-heading text-2xl font-semibold tabular-nums">{v}</dd>
              </div>
            ))}
          </dl>
          {u.totals.unknown_cost_calls > 0 && (
            <p className="text-sm text-muted-foreground">
              <Badge variant="outline" className="mr-1 bg-marigold-soft">
                Note
              </Badge>
              {u.totals.unknown_cost_calls} call{u.totals.unknown_cost_calls === 1 ? "" : "s"} used
              a model without a known price;{" "}
              {u.totals.unknown_cost_calls === 1 ? "it isn't" : "they aren't"} included in the cost.
            </p>
          )}
          <div className="grid gap-6 lg:grid-cols-2">
            <UsageTable title="By task" rows={u.by_task} />
            <UsageTable title="By model" rows={u.by_model} />
          </div>
        </>
      )}
    </section>
  );
}

function UsageTable({ title, rows }: { title: string; rows: Schemas["UsageRow"][] }) {
  return (
    <div>
      <h3 className="mb-2 text-sm font-medium">{title}</h3>
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b text-left text-xs text-muted-foreground">
            <th className="py-1.5 font-normal">Name</th>
            <th className="py-1.5 text-right font-normal">Calls</th>
            <th className="py-1.5 text-right font-normal">Tokens</th>
            <th className="py-1.5 text-right font-normal">Cost</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.key} className="border-b last:border-0">
              <td className="max-w-0 truncate py-1.5 pr-2">
                <code className="text-xs">{r.key}</code>
              </td>
              <td className="py-1.5 text-right tabular-nums">
                {num(r.calls)}
                {r.errors > 0 && <span className="text-rose"> ({r.errors} failed)</span>}
              </td>
              <td className="py-1.5 text-right tabular-nums">{num(r.tokens_in + r.tokens_out)}</td>
              <td className="py-1.5 text-right tabular-nums">{usd(r.cost_usd)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
