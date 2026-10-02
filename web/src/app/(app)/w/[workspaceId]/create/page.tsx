"use client";

import {
  AtSign,
  BriefcaseBusiness,
  Camera,
  Check,
  GalleryHorizontalEnd,
  Loader2,
  Mail,
  Sparkles,
  Square,
} from "lucide-react";
import { useParams } from "next/navigation";
import { useRef, useState } from "react";

import { AIErrorState } from "@/components/ai-error";
import { VariantCard } from "@/components/content/variant-card";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import type { Schemas } from "@/lib/api/client";
import { useBrandKit, useWorkspace } from "@/lib/api/hooks";
import { postSSE } from "@/lib/api/stream";
import { cn } from "@/lib/utils";

type Channel = Schemas["Channel"];

const CHANNELS: { value: Channel; label: string; icon: typeof Camera }[] = [
  { value: "instagram_post", label: "Instagram post", icon: Camera },
  { value: "instagram_carousel", label: "Carousel", icon: GalleryHorizontalEnd },
  { value: "linkedin_post", label: "LinkedIn", icon: BriefcaseBusiness },
  { value: "x_post", label: "X", icon: AtSign },
  { value: "email", label: "Email", icon: Mail },
];

const EXAMPLES = [
  "Diwali offer: 15% off gift hampers until 2 Nov",
  "New monsoon menu launch",
  "Hiring post: we need two baristas",
  "Weekend event announcement",
  "Thank regular customers",
];

type Step = { key: string; label: string; status: "running" | "done" };
type DraftVariant = { label: string; angle: string; content: Record<string, unknown> };
type Item = Schemas["ContentItemOut"];

export default function CreateContentPage() {
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const ws = useWorkspace(workspaceId);
  const kit = useBrandKit(workspaceId);
  const [channel, setChannel] = useState<Channel>("instagram_post");
  const [brief, setBrief] = useState("");
  const [n, setN] = useState(3);
  const [critique, setCritique] = useState(true);
  const [running, setRunning] = useState(false);
  const [steps, setSteps] = useState<Step[]>([]);
  const [drafts, setDrafts] = useState<DraftVariant[]>([]);
  const [items, setItems] = useState<Item[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [resultChannel, setResultChannel] = useState<Channel>(channel);
  const abort = useRef<AbortController | null>(null);

  const brand = {
    name: ws.data?.name ?? "Your business",
    logoUrl: kit.data?.logo_url,
    primary: kit.data?.primary_color,
  };

  async function generate() {
    abort.current?.abort();
    const controller = new AbortController();
    abort.current = controller;
    setRunning(true);
    setSteps([]);
    setDrafts([]);
    setItems([]);
    setError(null);
    setResultChannel(channel);
    try {
      await postSSE(
        `/api/v1/workspaces/${workspaceId}/content/generate`,
        { channel, brief, n_variants: n, critique },
        (event, data) => {
          if (event === "step") {
            const s = data as Step;
            setSteps((prev) => {
              const i = prev.findIndex((p) => p.key === s.key);
              return i === -1 ? [...prev, s] : prev.map((p, j) => (j === i ? s : p));
            });
          } else if (event === "variant") {
            setDrafts((prev) => [...prev, data as DraftVariant]);
          } else if (event === "item") {
            setItems((prev) => [...prev, data as Item]);
          } else if (event === "error") {
            setError(data);
          }
        },
        controller.signal,
      );
    } catch (err) {
      setError(err);
    } finally {
      setRunning(false);
      setSteps((prev) => prev.map((s) => ({ ...s, status: "done" })));
    }
  }

  const showDrafts = items.length === 0 && drafts.length > 0;
  const tooShort = brief.trim().length < 5;

  return (
    <>
      <PageHeader
        title="Create content"
        description="Describe what you want to say. You’ll get distinct takes, each reviewed against your brand voice and the platform’s rules."
      />
      <div className="grid gap-8 xl:grid-cols-[minmax(0,26rem)_minmax(0,1fr)]">
        <form
          className="space-y-6"
          onSubmit={(e) => {
            e.preventDefault();
            if (!tooShort && !running) void generate();
          }}
        >
          <fieldset>
            <legend className="mb-2 text-sm font-medium">Channel</legend>
            <div role="radiogroup" className="grid grid-cols-2 gap-2 sm:grid-cols-3">
              {CHANNELS.map((c) => (
                <button
                  key={c.value}
                  type="button"
                  role="radio"
                  aria-checked={channel === c.value}
                  onClick={() => setChannel(c.value)}
                  className={cn(
                    "flex items-center gap-2 rounded-md border bg-card px-3 py-2 text-left text-sm transition-colors hover:border-ring focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
                    channel === c.value && "border-foreground ring-1 ring-foreground",
                  )}
                >
                  <c.icon className="size-4 text-muted-foreground" aria-hidden />
                  {c.label}
                </button>
              ))}
            </div>
          </fieldset>

          <div className="space-y-2">
            <Label htmlFor="brief">Brief</Label>
            <Textarea
              id="brief"
              rows={5}
              value={brief}
              onChange={(e) => setBrief(e.target.value)}
              placeholder="What's happening, who it's for, and anything that must be mentioned (prices, dates, offers)."
            />
            <div className="flex flex-wrap gap-1.5">
              {EXAMPLES.map((ex) => (
                <button
                  key={ex}
                  type="button"
                  onClick={() => setBrief(ex)}
                  className="rounded-full border bg-card px-2.5 py-1 text-xs text-muted-foreground hover:border-ring hover:text-foreground"
                >
                  {ex}
                </button>
              ))}
            </div>
          </div>

          <div className="flex flex-wrap items-end gap-6">
            <div className="space-y-2">
              <Label htmlFor="variants">Variants</Label>
              <Select value={String(n)} onValueChange={(v) => setN(Number(v))}>
                <SelectTrigger id="variants" className="w-28">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {[1, 2, 3, 4].map((x) => (
                    <SelectItem key={x} value={String(x)}>
                      {x}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <label className="flex items-center gap-2 pb-1.5 text-sm">
              <Switch checked={critique} onCheckedChange={setCritique} />
              Review and revise
            </label>
          </div>

          <div className="flex gap-2">
            <Button type="submit" size="lg" disabled={tooShort || running}>
              {running ? (
                <Loader2 className="size-4 animate-spin" aria-hidden />
              ) : (
                <Sparkles className="size-4" aria-hidden />
              )}
              {running ? "Generating…" : "Generate"}
            </Button>
            {running && (
              <Button
                type="button"
                size="lg"
                variant="outline"
                onClick={() => abort.current?.abort()}
              >
                <Square className="size-3.5" aria-hidden /> Stop
              </Button>
            )}
          </div>

          {steps.length > 0 && (
            <ol
              className="space-y-1.5 rounded-lg border bg-card p-4 text-sm"
              aria-live="polite"
              aria-label="Progress"
            >
              {steps.map((s) => (
                <li key={s.key} className="flex items-center gap-2">
                  {s.status === "running" ? (
                    <Loader2 className="size-3.5 animate-spin text-marigold" aria-hidden />
                  ) : (
                    <Check className="size-3.5 text-leaf" aria-hidden />
                  )}
                  <span className={s.status === "running" ? "" : "text-muted-foreground"}>
                    {s.label}
                  </span>
                </li>
              ))}
            </ol>
          )}
        </form>

        <section aria-label="Results" className="min-w-0 space-y-4">
          {error !== null && <AIErrorState error={error} onRetry={() => void generate()} />}
          {items.length === 0 && drafts.length === 0 && !running && error === null && (
            <div className="grid min-h-64 place-items-center rounded-xl border border-dashed p-8 text-center text-sm text-muted-foreground">
              <p className="max-w-sm">
                Your variants will appear here as they&apos;re written. They&apos;re saved as
                drafts, so nothing is published until you approve it.
              </p>
            </div>
          )}
          <div className="grid gap-4 2xl:grid-cols-2">
            {showDrafts
              ? drafts.map((d) => (
                  <VariantCard
                    key={`draft-${d.label}`}
                    workspaceId={workspaceId}
                    channel={resultChannel}
                    label={d.label}
                    angle={d.angle}
                    content={d.content}
                    brand={brand}
                    pending={running}
                  />
                ))
              : items.map((it) => (
                  <VariantCard
                    key={it.id}
                    workspaceId={workspaceId}
                    channel={it.channel}
                    label={it.variant_label ?? "A"}
                    angle={it.title ?? ""}
                    content={it.payload as Record<string, unknown>}
                    item={it}
                    brand={brand}
                  />
                ))}
          </div>
        </section>
      </div>
    </>
  );
}
