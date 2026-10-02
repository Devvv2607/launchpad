"use client";

import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import { Field } from "@/components/auth-form";
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
import { xWeightedLength } from "@/lib/text";
import { cn } from "@/lib/utils";

/** Editable structured content. Shape matches the API's per-channel schema. */
export type Content = Record<string, unknown>;

function Count({ n, max, soft }: { n: number; max: number; soft?: number }) {
  return (
    <span
      className={cn(
        "text-xs tabular-nums",
        n > max
          ? "font-medium text-rose"
          : soft && n > soft
            ? "text-foreground"
            : "text-muted-foreground",
      )}
    >
      {n}/{max}
    </span>
  );
}

function Labelled({
  label,
  counter,
  children,
}: {
  label: string;
  counter?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-sm font-medium">{label}</span>
        {counter}
      </div>
      {children}
    </div>
  );
}

const tagsToText = (t: unknown) => (Array.isArray(t) ? (t as string[]).join(" ") : "");
const textToTags = (s: string) =>
  s
    .split(/[\s,]+/)
    .map((x) => x.trim())
    .filter(Boolean)
    .map((x) => (x.startsWith("#") ? x : `#${x}`));

export function ContentEditor({
  channel,
  initial,
  saving,
  onSave,
  onCancel,
}: {
  channel: string;
  initial: Content;
  saving: boolean;
  onSave: (content: Content) => void;
  onCancel: () => void;
}) {
  const { rendered: _rendered, ...rest } = initial; // server-rendered email HTML isn't editable
  void _rendered;
  const [c, setC] = useState<Content>(rest);
  const [tags, setTags] = useState(tagsToText(rest.hashtags));
  const set = (k: string, v: unknown) => setC((prev) => ({ ...prev, [k]: v }));
  const s = (k: string) => (typeof c[k] === "string" ? (c[k] as string) : "");
  const tagList = textToTags(tags);

  const body = (() => {
    switch (channel) {
      case "instagram_post":
      case "instagram_carousel": {
        const total = s("caption").length + (tagList.length ? 2 + tagList.join(" ").length : 0);
        return (
          <>
            <Labelled label="Caption" counter={<Count n={total} max={2200} />}>
              <Textarea
                rows={6}
                value={s("caption")}
                onChange={(e) => set("caption", e.target.value)}
                aria-label="Caption"
              />
              <p className="text-xs text-muted-foreground">
                The feed shows the first 125 characters
                {s("caption").length > 125 && <>: “{s("caption").slice(0, 125)}…”</>}
              </p>
            </Labelled>
            {channel === "instagram_carousel" && (
              <SlidesEditor slides={c.slides} onChange={(v) => set("slides", v)} />
            )}
            <Labelled label="Call to action">
              <Input
                value={s("cta")}
                onChange={(e) => set("cta", e.target.value)}
                aria-label="Call to action"
              />
            </Labelled>
            <Labelled label="Image idea">
              <Textarea
                rows={2}
                value={s("image_idea")}
                onChange={(e) => set("image_idea", e.target.value)}
                aria-label="Image idea"
              />
            </Labelled>
            {channel === "instagram_post" && (
              <Labelled label="Alt text">
                <Input
                  value={s("alt_text")}
                  onChange={(e) => set("alt_text", e.target.value)}
                  aria-label="Alt text"
                />
              </Labelled>
            )}
          </>
        );
      }
      case "linkedin_post":
        return (
          <>
            <Labelled label="Post" counter={<Count n={s("text").length} max={3000} />}>
              <Textarea
                rows={8}
                value={s("text")}
                onChange={(e) => set("text", e.target.value)}
                aria-label="Post text"
              />
              <p className="text-xs text-muted-foreground">
                “see more” appears after ~210 characters (~140 on mobile).
              </p>
            </Labelled>
            <Labelled label="Call to action">
              <Input
                value={s("cta")}
                onChange={(e) => set("cta", e.target.value)}
                aria-label="Call to action"
              />
            </Labelled>
          </>
        );
      case "x_post": {
        const posts = Array.isArray(c.posts) ? (c.posts as string[]) : [];
        return (
          <>
            <Field id="x_mode" label="Format">
              <Select value={s("mode") || "single"} onValueChange={(v) => set("mode", v)}>
                <SelectTrigger id="x_mode" className="w-40">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="single">Single post</SelectItem>
                  <SelectItem value="thread">Thread</SelectItem>
                </SelectContent>
              </Select>
            </Field>
            {posts.map((p, i) => {
              const withTags =
                i === posts.length - 1 && tagList.length ? `${p} ${tagList.join(" ")}` : p;
              return (
                <Labelled
                  key={i}
                  label={`Post ${i + 1}`}
                  counter={<Count n={xWeightedLength(withTags)} max={280} />}
                >
                  <div className="flex gap-2">
                    <Textarea
                      rows={3}
                      value={p}
                      aria-label={`Post ${i + 1}`}
                      onChange={(e) =>
                        set(
                          "posts",
                          posts.map((x, j) => (j === i ? e.target.value : x)),
                        )
                      }
                    />
                    {posts.length > 1 && (
                      <Button
                        type="button"
                        size="icon-sm"
                        variant="ghost"
                        aria-label={`Remove post ${i + 1}`}
                        onClick={() =>
                          set(
                            "posts",
                            posts.filter((_, j) => j !== i),
                          )
                        }
                      >
                        <Trash2 className="size-4" />
                      </Button>
                    )}
                  </div>
                </Labelled>
              );
            })}
            {s("mode") === "thread" && posts.length < 10 && (
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => set("posts", [...posts, ""])}
              >
                <Plus className="size-4" /> Add post
              </Button>
            )}
          </>
        );
      }
      case "email":
        return <EmailEditor content={c} onChange={setC} />;
      default:
        return null;
    }
  })();

  const hasTags = channel !== "email";
  const tagMax = channel === "linkedin_post" ? 5 : channel === "x_post" ? 2 : 30;
  return (
    <form
      className="space-y-4"
      onSubmit={(e) => {
        e.preventDefault();
        onSave(hasTags ? { ...c, hashtags: tagList } : c);
      }}
    >
      {body}
      {hasTags && (
        <Labelled label="Hashtags" counter={<Count n={tagList.length} max={tagMax} />}>
          <Input
            value={tags}
            onChange={(e) => setTags(e.target.value)}
            placeholder="#MumbaiRains #chai"
            aria-label="Hashtags"
          />
        </Labelled>
      )}
      <div className="flex gap-2">
        <Button type="submit" disabled={saving}>
          {saving ? "Saving…" : "Save draft"}
        </Button>
        <Button type="button" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

type Slide = { headline: string; body: string };

function SlidesEditor({ slides, onChange }: { slides: unknown; onChange: (v: Slide[]) => void }) {
  const list = Array.isArray(slides) ? (slides as Slide[]) : [];
  const update = (i: number, k: keyof Slide, v: string) =>
    onChange(list.map((s, j) => (j === i ? { ...s, [k]: v } : s)));
  return (
    <div className="space-y-3">
      <div className="flex items-baseline justify-between">
        <span className="text-sm font-medium">Slides</span>
        <span
          className={cn(
            "text-xs",
            list.length < 5 || list.length > 10 ? "text-rose" : "text-muted-foreground",
          )}
        >
          {list.length} (5-10)
        </span>
      </div>
      {list.map((s, i) => (
        <div key={i} className="space-y-2 rounded-md border p-3">
          <div className="flex items-center gap-2">
            <span className="w-6 text-xs text-muted-foreground">{i + 1}</span>
            <Input
              value={s.headline}
              onChange={(e) => update(i, "headline", e.target.value)}
              aria-label={`Slide ${i + 1} headline`}
            />
            <Count n={s.headline.length} max={60} />
            <Button
              type="button"
              size="icon-sm"
              variant="ghost"
              aria-label={`Remove slide ${i + 1}`}
              onClick={() => onChange(list.filter((_, j) => j !== i))}
            >
              <Trash2 className="size-4" />
            </Button>
          </div>
          <div className="flex items-start gap-2 pl-8">
            <Textarea
              rows={2}
              value={s.body}
              onChange={(e) => update(i, "body", e.target.value)}
              aria-label={`Slide ${i + 1} body`}
            />
            <Count n={s.body.length} max={220} />
          </div>
        </div>
      ))}
      {list.length < 10 && (
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={() => onChange([...list, { headline: "", body: "" }])}
        >
          <Plus className="size-4" /> Add slide
        </Button>
      )}
    </div>
  );
}

type Section = {
  type: string;
  heading?: string | null;
  body?: string | null;
  items?: string[];
  button_label?: string | null;
  button_url?: string | null;
};

function EmailEditor({ content, onChange }: { content: Content; onChange: (c: Content) => void }) {
  const subjects = Array.isArray(content.subject_variants)
    ? (content.subject_variants as string[])
    : [];
  const sections = Array.isArray(content.sections) ? (content.sections as Section[]) : [];
  const pre = typeof content.preheader === "string" ? content.preheader : "";
  const setSection = (i: number, patch: Partial<Section>) =>
    onChange({ ...content, sections: sections.map((s, j) => (j === i ? { ...s, ...patch } : s)) });
  return (
    <>
      {subjects.map((s, i) => (
        <Labelled
          key={i}
          label={`Subject ${String.fromCharCode(65 + i)}`}
          counter={<Count n={s.length} max={100} soft={60} />}
        >
          <Input
            value={s}
            aria-label={`Subject ${i + 1}`}
            onChange={(e) =>
              onChange({
                ...content,
                subject_variants: subjects.map((x, j) => (j === i ? e.target.value : x)),
              })
            }
          />
        </Labelled>
      ))}
      <Labelled label="Preheader" counter={<Count n={pre.length} max={130} />}>
        <Input
          value={pre}
          aria-label="Preheader"
          onChange={(e) => onChange({ ...content, preheader: e.target.value })}
        />
      </Labelled>
      {sections.map((s, i) => (
        <div key={i} className="space-y-2 rounded-md border p-3">
          <p className="text-xs font-medium tracking-wide text-muted-foreground capitalize">
            {s.type} section
          </p>
          {s.type !== "quote" && (
            <Input
              placeholder="Heading"
              value={s.heading ?? ""}
              aria-label={`Section ${i + 1} heading`}
              onChange={(e) => setSection(i, { heading: e.target.value || null })}
            />
          )}
          {s.type !== "bullets" && s.type !== "cta" && (
            <Textarea
              rows={3}
              placeholder="Body"
              value={s.body ?? ""}
              aria-label={`Section ${i + 1} body`}
              onChange={(e) => setSection(i, { body: e.target.value || null })}
            />
          )}
          {s.type === "bullets" && (
            <Textarea
              rows={3}
              placeholder="One item per line"
              value={(s.items ?? []).join("\n")}
              aria-label={`Section ${i + 1} items`}
              onChange={(e) =>
                setSection(i, { items: e.target.value.split("\n").filter((x) => x.trim()) })
              }
            />
          )}
          {s.type === "cta" && (
            <div className="grid gap-2 sm:grid-cols-2">
              <Input
                placeholder="Button label"
                value={s.button_label ?? ""}
                aria-label="Button label"
                onChange={(e) => setSection(i, { button_label: e.target.value || null })}
              />
              <Input
                placeholder="https://… (defaults to your website)"
                value={s.button_url ?? ""}
                aria-label="Button link"
                onChange={(e) => setSection(i, { button_url: e.target.value || null })}
              />
            </div>
          )}
        </div>
      ))}
    </>
  );
}
