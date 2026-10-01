"use client";

import { useParams } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { Field } from "@/components/auth-form";
import { PageHeader } from "@/components/page-header";
import { ErrorState, ListSkeleton } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, type Schemas } from "@/lib/api/client";
import { useBrandKit, useSaveBrandKit } from "@/lib/api/hooks";

type Form = {
  primary_color: string;
  secondary_color: string;
  heading_font: string;
  body_font: string;
  voice_tone: string;
  do_words: string;
  dont_words: string;
  sample_posts: string;
};

const toForm = (k: Schemas["BrandKitOut"]): Form => ({
  primary_color: k.primary_color ?? "",
  secondary_color: k.secondary_color ?? "",
  heading_font: k.heading_font ?? "",
  body_font: k.body_font ?? "",
  voice_tone: k.voice_tone ?? "",
  do_words: (k.do_words ?? []).join(", "),
  dont_words: (k.dont_words ?? []).join(", "),
  sample_posts: (k.sample_posts ?? []).join("\n---\n"),
});

const INLINE_FIELDS = new Set([
  "primary_color",
  "secondary_color",
  "voice_tone",
  "do_words",
  "dont_words",
  "sample_posts",
]);

const list = (s: string) =>
  s
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean);

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
        <BrandKitForm workspaceId={workspaceId} kit={kit.data} />
      )}
    </>
  );
}

function BrandKitForm({ workspaceId, kit }: { workspaceId: string; kit: Schemas["BrandKitOut"] }) {
  const save = useSaveBrandKit(workspaceId);
  const [form, setForm] = useState<Form>(() => toForm(kit));

  const set = (k: keyof Form) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));
  const fe = save.error instanceof ApiError ? save.error.fieldErrors() : {};

  function submit(e: React.FormEvent) {
    e.preventDefault();
    save.mutate(
      {
        logo_asset_id: kit.logo_asset_id ?? null,
        primary_color: form.primary_color || null,
        secondary_color: form.secondary_color || null,
        heading_font: form.heading_font || null,
        body_font: form.body_font || null,
        voice_tone: form.voice_tone || null,
        do_words: list(form.do_words),
        dont_words: list(form.dont_words),
        sample_posts: form.sample_posts
          .split(/\n-{3,}\n/)
          .map((s) => s.trim())
          .filter(Boolean),
      },
      { onSuccess: () => toast.success("Brand kit saved") },
    );
  }

  return (
    <form onSubmit={submit} className="max-w-2xl space-y-10">
      <fieldset className="space-y-6">
        <legend className="mb-4 font-heading text-lg font-semibold">Look</legend>
        <div className="grid gap-6 sm:grid-cols-2">
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
        </div>
      </fieldset>

      <fieldset className="space-y-6">
        <legend className="mb-4 font-heading text-lg font-semibold">Voice</legend>
        <Field id="voice_tone" label="Voice and tone" error={fe.voice_tone}>
          <Textarea id="voice_tone" rows={4} value={form.voice_tone} onChange={set("voice_tone")} />
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
        <Field
          id="sample_posts"
          label="Posts that sound like you"
          hint="Paste up to 10 past captions. Separate them with a line containing only ---"
          error={fe.sample_posts}
        >
          <Textarea
            id="sample_posts"
            rows={8}
            value={form.sample_posts}
            onChange={set("sample_posts")}
          />
        </Field>
      </fieldset>

      {save.error && Object.keys(fe).every((k) => !INLINE_FIELDS.has(k)) && (
        <ErrorState error={save.error} />
      )}

      <div className="flex gap-3">
        <Button type="submit" disabled={save.isPending}>
          {save.isPending ? "Saving…" : "Save brand kit"}
        </Button>
        <Button type="button" variant="ghost" onClick={() => setForm(toForm(kit))}>
          Discard changes
        </Button>
      </div>
    </form>
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
          placeholder="#1E2250"
          onChange={onChange}
          className="font-mono uppercase"
        />
      </div>
    </Field>
  );
}
