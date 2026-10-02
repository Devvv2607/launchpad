"use client";

import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { Field } from "@/components/auth-form";
import { KnowledgePanel } from "@/components/brand/knowledge-panel";
import { type ColorRole, LogoPanel } from "@/components/brand/logo-panel";
import {
  type VoiceProfile,
  VoiceFromSamples,
  VoiceProfileEditor,
  splitSamples,
} from "@/components/brand/voice-panel";
import { PageHeader } from "@/components/page-header";
import { ErrorState, ListSkeleton } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, type Schemas } from "@/lib/api/client";
import { useBrandKit, useSaveBrandKit } from "@/lib/api/hooks";

type Form = {
  primary_color: string;
  secondary_color: string;
  accent_colors: string[];
  heading_font: string;
  body_font: string;
  voice_tone: string;
  do_words: string;
  dont_words: string;
  sample_posts: string;
  voice_profile: VoiceProfile | null;
};

const toForm = (k: Schemas["BrandKitOut"]): Form => ({
  primary_color: k.primary_color ?? "",
  secondary_color: k.secondary_color ?? "",
  accent_colors: k.accent_colors ?? [],
  heading_font: k.heading_font ?? "",
  body_font: k.body_font ?? "",
  voice_tone: k.voice_tone ?? "",
  do_words: (k.do_words ?? []).join(", "),
  dont_words: (k.dont_words ?? []).join(", "),
  sample_posts: (k.sample_posts ?? []).join("\n---\n"),
  voice_profile: k.voice_profile ?? null,
});

const list = (s: string) =>
  s
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean);

const TABS = ["identity", "voice", "knowledge"] as const;
type Tab = (typeof TABS)[number];

export default function BrandKitPage() {
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const kit = useBrandKit(workspaceId);
  return (
    <>
      <PageHeader
        title="Brand kit"
        description="The agent reads this before writing anything. The more specific, the less editing you’ll do."
      />
      {kit.error ? (
        <ErrorState error={kit.error} onRetry={() => kit.refetch()} />
      ) : !kit.data ? (
        <ListSkeleton rows={6} />
      ) : (
        <BrandKitEditor workspaceId={workspaceId} kit={kit.data} />
      )}
    </>
  );
}

function BrandKitEditor({
  workspaceId,
  kit,
}: {
  workspaceId: string;
  kit: Schemas["BrandKitOut"];
}) {
  const router = useRouter();
  const params = useSearchParams();
  const initialTab = (TABS as readonly string[]).includes(params.get("tab") ?? "")
    ? (params.get("tab") as Tab)
    : "identity";
  const [tab, setTab] = useState<Tab>(initialTab);
  const save = useSaveBrandKit(workspaceId);
  const [form, setForm] = useState<Form>(() => toForm(kit));
  const saved = useMemo(() => JSON.stringify(toForm(kit)), [kit]);
  const dirty = JSON.stringify(form) !== saved;

  const set = (k: keyof Form) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));
  const fe = save.error instanceof ApiError ? save.error.fieldErrors() : {};

  function applyColor(role: ColorRole, hex: string) {
    setForm((f) =>
      role === "accent"
        ? { ...f, accent_colors: Array.from(new Set([...f.accent_colors, hex])).slice(0, 6) }
        : { ...f, [role]: hex },
    );
  }

  function applyAll(palette: Schemas["PaletteColorOut"][]) {
    const byRole = (r: string) => palette.find((p) => p.role === r)?.hex;
    setForm((f) => ({
      ...f,
      primary_color: byRole("primary") ?? f.primary_color,
      secondary_color: byRole("secondary") ?? f.secondary_color,
      accent_colors: byRole("accent") ? [byRole("accent") as string] : f.accent_colors,
    }));
    toast("Suggested colours added to the form. Save to keep them.");
  }

  function submit() {
    save.mutate(
      {
        logo_asset_id: kit.logo_asset_id ?? null,
        primary_color: form.primary_color || null,
        secondary_color: form.secondary_color || null,
        accent_colors: form.accent_colors,
        heading_font: form.heading_font || null,
        body_font: form.body_font || null,
        voice_tone: form.voice_tone || null,
        do_words: list(form.do_words),
        dont_words: list(form.dont_words),
        sample_posts: splitSamples(form.sample_posts),
        voice_profile: form.voice_profile,
      },
      {
        onSuccess: (k) => {
          setForm(toForm(k));
          toast.success("Brand kit saved");
        },
      },
    );
  }

  return (
    <Tabs
      value={tab}
      onValueChange={(v) => {
        setTab(v as Tab);
        router.replace(`?tab=${v}`, { scroll: false });
      }}
      className="max-w-4xl gap-8"
    >
      <TabsList>
        <TabsTrigger value="identity">Identity</TabsTrigger>
        <TabsTrigger value="voice">Voice</TabsTrigger>
        <TabsTrigger value="knowledge">Knowledge</TabsTrigger>
      </TabsList>

      <TabsContent value="identity" className="space-y-10">
        <LogoPanel
          workspaceId={workspaceId}
          logoUrl={kit.logo_url}
          palette={kit.logo_palette ?? []}
          hasColors={Boolean(
            form.primary_color || form.secondary_color || form.accent_colors.length,
          )}
          onApply={applyColor}
          onApplyAll={applyAll}
        />
        <fieldset className="grid gap-6 sm:grid-cols-2">
          <legend className="mb-4 font-heading text-lg font-semibold">Colours and type</legend>
          <Swatch
            id="primary"
            label="Primary colour"
            value={form.primary_color}
            onChange={set("primary_color")}
            error={fe.primary_color}
          />
          <Swatch
            id="secondary"
            label="Secondary colour"
            value={form.secondary_color}
            onChange={set("secondary_color")}
            error={fe.secondary_color}
          />
          <div className="sm:col-span-2">
            <p className="mb-1.5 text-sm font-medium">Accent colours</p>
            {form.accent_colors.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                None yet. Pick one from your logo above.
              </p>
            ) : (
              <ul className="flex flex-wrap gap-2">
                {form.accent_colors.map((c) => (
                  <li
                    key={c}
                    className="flex items-center gap-2 rounded-md border bg-card py-1 pr-1 pl-2 text-sm"
                  >
                    <span
                      className="size-4 rounded ring-1 ring-foreground/15"
                      style={{ background: c }}
                      aria-hidden
                    />
                    <code>{c}</code>
                    <Button
                      type="button"
                      size="icon-xs"
                      variant="ghost"
                      aria-label={`Remove ${c}`}
                      onClick={() =>
                        setForm((f) => ({
                          ...f,
                          accent_colors: f.accent_colors.filter((x) => x !== c),
                        }))
                      }
                    >
                      ×
                    </Button>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <Field id="heading_font" label="Heading font">
            <Input
              id="heading_font"
              placeholder="e.g. Playfair Display"
              value={form.heading_font}
              onChange={set("heading_font")}
            />
          </Field>
          <Field id="body_font" label="Body font">
            <Input
              id="body_font"
              placeholder="e.g. Inter"
              value={form.body_font}
              onChange={set("body_font")}
            />
          </Field>
        </fieldset>
      </TabsContent>

      <TabsContent value="voice" className="space-y-8">
        <Field id="voice_tone" label="How does your brand sound?" error={fe.voice_tone}>
          <Textarea id="voice_tone" rows={3} value={form.voice_tone} onChange={set("voice_tone")} />
        </Field>
        <div className="grid gap-6 sm:grid-cols-2">
          <Field id="do_words" label="Words we use" hint="Comma-separated." error={fe.do_words}>
            <Input
              id="do_words"
              placeholder="fresh, handcrafted, neighbourhood"
              value={form.do_words}
              onChange={set("do_words")}
            />
          </Field>
          <Field
            id="dont_words"
            label="Words we avoid"
            hint="Comma-separated."
            error={fe.dont_words}
          >
            <Input
              id="dont_words"
              placeholder="cheap, synergy, best-in-class"
              value={form.dont_words}
              onChange={set("dont_words")}
            />
          </Field>
        </div>
        <VoiceFromSamples
          workspaceId={workspaceId}
          samplesText={form.sample_posts}
          onSamplesChange={(v) => setForm((f) => ({ ...f, sample_posts: v }))}
          onGenerated={(profile, samples) => {
            setForm((f) => ({
              ...f,
              voice_profile: profile,
              sample_posts: samples.join("\n---\n"),
            }));
            toast.success("Voice profile created and saved");
          }}
        />
        {form.voice_profile && (
          <VoiceProfileEditor
            value={form.voice_profile}
            onChange={(v) => setForm((f) => ({ ...f, voice_profile: v }))}
          />
        )}
      </TabsContent>

      <TabsContent value="knowledge">
        <KnowledgePanel workspaceId={workspaceId} />
      </TabsContent>

      {tab !== "knowledge" && (
        <div className="sticky bottom-0 -mx-4 flex flex-wrap items-center gap-3 border-t bg-background/95 px-4 py-3 backdrop-blur sm:-mx-8 sm:px-8">
          {save.error && !Object.keys(fe).length ? (
            <ErrorState error={save.error} className="w-full" />
          ) : (
            <p className="flex-1 text-sm text-muted-foreground">
              {dirty ? "You have unsaved changes." : "All changes saved."}
            </p>
          )}
          <Button
            type="button"
            variant="ghost"
            disabled={!dirty}
            onClick={() => setForm(toForm(kit))}
          >
            Discard
          </Button>
          <Button type="button" onClick={submit} disabled={save.isPending || !dirty}>
            {save.isPending ? "Saving…" : "Save brand kit"}
          </Button>
        </div>
      )}
    </Tabs>
  );
}

function Swatch({
  id,
  label,
  value,
  onChange,
  error,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  error?: string;
}) {
  const valid = /^#[0-9a-fA-F]{6}$/.test(value);
  return (
    <Field id={id} label={label} error={error}>
      <div className="flex items-center gap-3">
        <input
          type="color"
          aria-label={`${label} picker`}
          value={valid ? value : "#000000"}
          onChange={onChange}
          className="size-10 cursor-pointer rounded-md border bg-transparent p-1"
        />
        <Input
          id={id}
          value={value}
          placeholder="#RRGGBB"
          onChange={onChange}
          className="font-mono uppercase"
        />
      </div>
    </Field>
  );
}
