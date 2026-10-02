"use client";

import { Loader2, Sparkles } from "lucide-react";

import { Field } from "@/components/auth-form";
import { AIErrorState } from "@/components/ai-error";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import type { Schemas } from "@/lib/api/client";
import { useVoiceProfile } from "@/lib/api/hooks";

export type VoiceProfile = Schemas["VoiceProfile"];

const csv = (s: string) =>
  s
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean);

export function splitSamples(text: string): string[] {
  return text
    .split(/\n-{3,}\n/)
    .map((s) => s.trim())
    .filter(Boolean);
}

/** Generate a profile from past posts (saved server-side), then edit it in the form. */
export function VoiceFromSamples({
  workspaceId,
  samplesText,
  onSamplesChange,
  onGenerated,
}: {
  workspaceId: string;
  samplesText: string;
  onSamplesChange: (v: string) => void;
  onGenerated: (profile: VoiceProfile, samples: string[]) => void;
}) {
  const gen = useVoiceProfile(workspaceId);
  const samples = splitSamples(samplesText);
  const enough = samples.length >= 3 && samples.length <= 10;
  return (
    <div className="space-y-3">
      <Field
        id="sample_posts"
        label="Posts that sound like you"
        hint={`Paste 3-10 past captions, separated by a line containing only ---  (${samples.length} so far)`}
      >
        <Textarea
          id="sample_posts"
          rows={8}
          value={samplesText}
          onChange={(e) => onSamplesChange(e.target.value)}
          placeholder={
            "Rainy day? Cutting chai + a good book. See you at the shelf.\n---\nSunday reading circle is back at 9am!"
          }
        />
      </Field>
      <Button
        type="button"
        variant="outline"
        disabled={!enough || gen.isPending}
        onClick={() => gen.mutate(samples, { onSuccess: (p) => onGenerated(p, samples) })}
      >
        {gen.isPending ? (
          <>
            <Loader2 className="size-4 animate-spin" aria-hidden /> Analysing your posts…
          </>
        ) : (
          <>
            <Sparkles className="size-4" aria-hidden /> Build voice profile from these posts
          </>
        )}
      </Button>
      {gen.error && <AIErrorState error={gen.error} onRetry={() => gen.mutate(samples)} />}
    </div>
  );
}

export function VoiceProfileEditor({
  value,
  onChange,
}: {
  value: VoiceProfile;
  onChange: (v: VoiceProfile) => void;
}) {
  const set = <K extends keyof VoiceProfile>(k: K, v: VoiceProfile[K]) =>
    onChange({ ...value, [k]: v });
  return (
    <div className="space-y-5 rounded-lg border bg-card p-5">
      <div>
        <p className="font-medium">Voice profile</p>
        <p className="text-sm text-muted-foreground">
          Built from your posts. Edit anything that doesn&apos;t sound right.
        </p>
      </div>
      <Field id="vp_summary" label="Summary">
        <Textarea
          id="vp_summary"
          rows={2}
          value={value.summary}
          onChange={(e) => set("summary", e.target.value)}
        />
      </Field>
      <div className="grid gap-5 sm:grid-cols-2">
        <Field id="vp_tone" label="Tone" hint="Comma-separated, most characteristic first.">
          <Input
            id="vp_tone"
            value={value.tone_adjectives.join(", ")}
            onChange={(e) => set("tone_adjectives", csv(e.target.value))}
          />
        </Field>
        <Field id="vp_phrases" label="Signature phrases" hint="Comma-separated.">
          <Input
            id="vp_phrases"
            value={(value.signature_phrases ?? []).join(", ")}
            onChange={(e) => set("signature_phrases", csv(e.target.value))}
          />
        </Field>
        <Field id="vp_formality" label="Formality">
          <Select
            value={String(value.formality)}
            onValueChange={(v) => set("formality", Number(v))}
          >
            <SelectTrigger id="vp_formality" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {["Very casual", "Casual", "Balanced", "Polished", "Formal"].map((label, i) => (
                <SelectItem key={label} value={String(i + 1)}>
                  {i + 1} · {label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field id="vp_len" label="Sentences">
            <Select
              value={value.sentence_length}
              onValueChange={(v) => set("sentence_length", v as VoiceProfile["sentence_length"])}
            >
              <SelectTrigger id="vp_len" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {["short", "medium", "long", "mixed"].map((v) => (
                  <SelectItem key={v} value={v} className="capitalize">
                    {v}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          <Field id="vp_emoji" label="Emoji">
            <Select
              value={value.emoji_usage}
              onValueChange={(v) => set("emoji_usage", v as VoiceProfile["emoji_usage"])}
            >
              <SelectTrigger id="vp_emoji" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {["none", "rare", "moderate", "frequent"].map((v) => (
                  <SelectItem key={v} value={v} className="capitalize">
                    {v}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
        </div>
      </div>
    </div>
  );
}
