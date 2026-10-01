"use client";

import { BriefcaseBusiness, Camera, Check, Mail } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Field } from "@/components/auth-form";
import { Logo } from "@/components/logo";
import { ErrorState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { api, ApiError, unwrap, type Schemas } from "@/lib/api/client";
import { useCreateWorkspace } from "@/lib/api/hooks";
import { INDUSTRY_LABELS, type Industry } from "@/lib/labels";
import { cn } from "@/lib/utils";
import { rememberWorkspace } from "@/lib/workspace";

const STEPS = ["Business", "Industry", "Brand", "Channels"] as const;

type Draft = {
  name: string;
  description: string;
  website: string;
  locations: string;
  audience: string;
  industry: Industry | null;
  primary_color: string;
  secondary_color: string;
  voice_tone: string;
};

const EMPTY: Draft = {
  name: "",
  description: "",
  website: "",
  locations: "",
  audience: "",
  industry: null,
  primary_color: "#1E2250",
  secondary_color: "#F0A020",
  voice_tone: "",
};

export default function OnboardingPage() {
  const router = useRouter();
  const [step, setStep] = useState(0);
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [workspaceId, setWorkspaceId] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [saving, setSaving] = useState(false);
  const create = useCreateWorkspace();

  const set = (k: keyof Draft) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    setDraft((d) => ({ ...d, [k]: e.target.value }));

  const fieldErrors = error instanceof ApiError ? error.fieldErrors() : {};
  // Field errors we can't show next to an input on the current step must still be visible.
  const inlineFields =
    step === 0 ? ["name", "website", "locations", "audience", "description"] : [];
  const hasUnplacedError =
    error !== null && Object.keys(fieldErrors).every((k) => !inlineFields.includes(k));

  async function saveWorkspace() {
    if (!draft.industry) return;
    setSaving(true);
    setError(null);
    try {
      const body: Schemas["WorkspaceCreate"] = {
        name: draft.name,
        industry: draft.industry,
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Kolkata",
        description: draft.description || null,
        audience: draft.audience || null,
        website: draft.website || null,
        locations: draft.locations
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
      };
      // Re-running this step after a failed brand-kit save must not create a second workspace.
      const id = workspaceId ?? (await create.mutateAsync(body)).id;
      setWorkspaceId(id);
      rememberWorkspace(id);
      await unwrap(
        api.PUT("/api/v1/workspaces/{workspace_id}/brand-kit", {
          params: { path: { workspace_id: id } },
          body: {
            primary_color: draft.primary_color,
            secondary_color: draft.secondary_color,
            voice_tone: draft.voice_tone || null,
          },
        }),
      );
      setStep(3);
    } catch (e) {
      setError(e);
      const fe = e instanceof ApiError ? e.fieldErrors() : {};
      if (fe.name || fe.website || fe.locations || fe.audience) setStep(0);
    } finally {
      setSaving(false);
    }
  }

  const canContinue = [draft.name.trim().length > 0, draft.industry !== null, true, true][step];

  return (
    <div className="min-h-dvh">
      <header className="flex items-center justify-between border-b bg-card px-6 py-4">
        <Logo />
        <ol className="hidden items-center gap-6 text-sm sm:flex" aria-label="Setup progress">
          {STEPS.map((s, i) => (
            <li
              key={s}
              aria-current={i === step ? "step" : undefined}
              className={cn(
                "flex items-center gap-2",
                i === step ? "font-medium text-foreground" : "text-muted-foreground",
              )}
            >
              <span
                className={cn(
                  "grid size-6 place-items-center rounded-full border text-xs",
                  i < step && "border-leaf bg-leaf text-white",
                  i === step && "border-foreground",
                )}
              >
                {i < step ? <Check className="size-3.5" aria-hidden /> : i + 1}
              </span>
              {s}
            </li>
          ))}
        </ol>
      </header>

      <main className="mx-auto max-w-3xl px-6 py-12">
        {step === 0 && (
          <section className="space-y-6">
            <StepTitle
              title="Tell us about the business"
              body="The agent uses this in every piece of content it writes, so be specific."
            />
            <Field id="name" label="Business name" error={fieldErrors.name}>
              <Input id="name" value={draft.name} onChange={set("name")} autoFocus />
            </Field>
            <Field
              id="description"
              label="What do you sell?"
              hint="One or two sentences, e.g. “Specialty coffee and all-day brunch in Bandra.”"
            >
              <Textarea
                id="description"
                rows={3}
                value={draft.description}
                onChange={set("description")}
              />
            </Field>
            <div className="grid gap-6 sm:grid-cols-2">
              <Field
                id="locations"
                label="Where are you?"
                hint="Separate cities with commas."
                error={fieldErrors.locations}
              >
                <Input
                  id="locations"
                  placeholder="Mumbai, Pune"
                  value={draft.locations}
                  onChange={set("locations")}
                />
              </Field>
              <Field id="website" label="Website (optional)" error={fieldErrors.website}>
                <Input
                  id="website"
                  type="url"
                  placeholder="https://"
                  value={draft.website}
                  onChange={set("website")}
                />
              </Field>
            </div>
            <Field id="audience" label="Who are your customers?" error={fieldErrors.audience}>
              <Textarea
                id="audience"
                rows={3}
                placeholder="College students and young professionals who work from cafés"
                value={draft.audience}
                onChange={set("audience")}
              />
            </Field>
          </section>
        )}

        {step === 1 && (
          <section className="space-y-6">
            <StepTitle
              title="Pick your industry"
              body="This tunes hashtags, posting times and the kind of content that works."
            />
            <div role="radiogroup" aria-label="Industry" className="grid gap-3 sm:grid-cols-3">
              {(Object.keys(INDUSTRY_LABELS) as Industry[]).map((key) => {
                const selected = draft.industry === key;
                return (
                  <button
                    key={key}
                    type="button"
                    role="radio"
                    aria-checked={selected}
                    onClick={() => setDraft((d) => ({ ...d, industry: key }))}
                    className={cn(
                      "flex flex-col items-start justify-start rounded-lg border bg-card p-4 text-left transition-colors hover:border-ring focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
                      selected && "border-foreground ring-1 ring-foreground",
                    )}
                  >
                    <span className="block font-medium">{INDUSTRY_LABELS[key].label}</span>
                    <span className="mt-1 block text-xs text-muted-foreground">
                      {INDUSTRY_LABELS[key].hint}
                    </span>
                  </button>
                );
              })}
            </div>
          </section>
        )}

        {step === 2 && (
          <section className="space-y-6">
            <StepTitle
              title="Set your brand basics"
              body="Colours go on posters and emails; the voice guides every caption. You can refine all of this later in the brand kit."
            />
            <div className="grid gap-6 sm:grid-cols-2">
              <ColorField
                label="Primary colour"
                value={draft.primary_color}
                onChange={(v) => setDraft((d) => ({ ...d, primary_color: v }))}
              />
              <ColorField
                label="Secondary colour"
                value={draft.secondary_color}
                onChange={(v) => setDraft((d) => ({ ...d, secondary_color: v }))}
              />
            </div>
            <Field
              id="voice"
              label="How does your brand sound?"
              hint="e.g. “Warm and a little cheeky. Talks like a friend who knows good coffee. Never uses corporate jargon.”"
            >
              <Textarea id="voice" rows={4} value={draft.voice_tone} onChange={set("voice_tone")} />
            </Field>
          </section>
        )}

        {step === 3 && (
          <section className="space-y-6">
            <StepTitle
              title="Connect your channels"
              body="Optional. Without a connection, approved content is exported as a ready-to-post bundle you can download."
            />
            <ul className="divide-y rounded-lg border bg-card">
              {[
                { icon: Camera, name: "Instagram", note: "Business or creator account" },
                {
                  icon: BriefcaseBusiness,
                  name: "LinkedIn",
                  note: "Personal profile or company page",
                },
                { icon: Mail, name: "Email", note: "Send campaigns through Resend" },
              ].map((c) => (
                <li key={c.name} className="flex items-center gap-4 p-4">
                  <c.icon className="size-5 text-muted-foreground" aria-hidden />
                  <div className="flex-1">
                    <p className="font-medium">{c.name}</p>
                    <p className="text-sm text-muted-foreground">{c.note}</p>
                  </div>
                  <Button variant="outline" size="sm" disabled>
                    Not available yet
                  </Button>
                </li>
              ))}
            </ul>
          </section>
        )}

        {hasUnplacedError && <ErrorState className="mt-6" error={error} />}

        <div className="mt-10 flex items-center justify-between">
          {step > 0 && step < 3 ? (
            <Button variant="ghost" onClick={() => setStep((s) => s - 1)}>
              Back
            </Button>
          ) : (
            <span />
          )}
          {step < 2 && (
            <Button onClick={() => setStep((s) => s + 1)} disabled={!canContinue}>
              Continue
            </Button>
          )}
          {step === 2 && (
            <Button onClick={saveWorkspace} disabled={saving}>
              {saving ? "Creating workspace…" : "Create workspace"}
            </Button>
          )}
          {step === 3 && workspaceId && (
            <Button onClick={() => router.replace(`/w/${workspaceId}`)}>Go to dashboard</Button>
          )}
        </div>
      </main>
    </div>
  );
}

function StepTitle({ title, body }: { title: string; body: string }) {
  return (
    <div>
      <h1 className="text-3xl font-semibold">{title}</h1>
      <p className="mt-2 max-w-prose text-muted-foreground">{body}</p>
    </div>
  );
}

function ColorField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
}) {
  const id = label.toLowerCase().replace(/\s+/g, "-");
  return (
    <Field id={id} label={label}>
      <div className="flex items-center gap-3">
        <input
          type="color"
          aria-label={`${label} picker`}
          value={value}
          onChange={(e) => onChange(e.target.value.toUpperCase())}
          className="size-10 cursor-pointer rounded-md border bg-transparent p-1"
        />
        <Input
          id={id}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="font-mono uppercase"
        />
      </div>
    </Field>
  );
}
