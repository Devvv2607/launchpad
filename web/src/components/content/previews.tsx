"use client";

import {
  Bookmark,
  ChevronLeft,
  ChevronRight,
  Globe2,
  Heart,
  ImageOff,
  MessageCircle,
  Monitor,
  Repeat2,
  Send,
  Smartphone,
  ThumbsUp,
} from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { xWeightedLength } from "@/lib/text";
import { cn } from "@/lib/utils";

export type Brand = { name: string; logoUrl?: string | null; primary?: string | null };

/** Fields are untyped JSON from the API; these previews read them defensively. */
type Content = Record<string, unknown>;
const str = (v: unknown) => (typeof v === "string" ? v : "");
const arr = <T,>(v: unknown) => (Array.isArray(v) ? (v as T[]) : []);

function Avatar({ brand, size = "size-8" }: { brand: Brand; size?: string }) {
  return brand.logoUrl ? (
    // eslint-disable-next-line @next/next/no-img-element -- signed, short-lived URL
    <img
      src={brand.logoUrl}
      alt=""
      className={cn(size, "rounded-full border bg-white object-contain")}
    />
  ) : (
    <span
      className={cn(
        size,
        "grid place-items-center rounded-full font-heading text-sm font-semibold text-white",
      )}
      style={{ background: brand.primary || "#1E2250" }}
      aria-hidden
    >
      {brand.name.charAt(0).toUpperCase()}
    </span>
  );
}

function handle(name: string) {
  return (
    name
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "")
      .slice(0, 15) || "yourbusiness"
  );
}

function Folded({ text, fold, more }: { text: string; fold: number; more: string }) {
  const [open, setOpen] = useState(false);
  if (open || text.length <= fold) return <>{text}</>;
  return (
    <>
      {text.slice(0, fold).trimEnd()}
      <button
        type="button"
        className="ml-0.5 text-muted-foreground hover:underline"
        onClick={() => setOpen(true)}
      >
        … {more}
      </button>
    </>
  );
}

function NoImage({ idea, ratio }: { idea: string; ratio: "1:1" | "4:5" }) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-2 bg-muted px-6 text-center text-muted-foreground",
        ratio === "1:1" ? "aspect-square" : "aspect-[4/5]",
      )}
    >
      <ImageOff className="size-6" aria-hidden />
      <p className="text-xs font-medium">No image yet</p>
      {idea && <p className="line-clamp-4 text-xs">{idea}</p>}
    </div>
  );
}

function Hashtags({ tags }: { tags: string[] }) {
  if (!tags.length) return null;
  return <span className="text-[#00376b] dark:text-[#e0f1ff]">{" " + tags.join(" ")}</span>;
}

export function InstagramPreview({ content, brand }: { content: Content; brand: Brand }) {
  const [ratio, setRatio] = useState<"1:1" | "4:5">("1:1");
  const caption = str(content.caption);
  return (
    <figure className="overflow-hidden rounded-lg border bg-card text-sm">
      <div className="flex items-center gap-2 px-3 py-2">
        <Avatar brand={brand} />
        <span className="flex-1 font-semibold">{handle(brand.name)}</span>
        <ToggleGroup
          type="single"
          size="sm"
          value={ratio}
          onValueChange={(v) => v && setRatio(v as "1:1" | "4:5")}
          aria-label="Image shape"
        >
          <ToggleGroupItem value="1:1" className="h-6 px-1.5 text-xs">
            1:1
          </ToggleGroupItem>
          <ToggleGroupItem value="4:5" className="h-6 px-1.5 text-xs">
            4:5
          </ToggleGroupItem>
        </ToggleGroup>
      </div>
      <NoImage idea={str(content.image_idea)} ratio={ratio} />
      <div className="flex gap-4 px-3 pt-2.5" aria-hidden>
        <Heart className="size-5" />
        <MessageCircle className="size-5" />
        <Send className="size-5" />
        <Bookmark className="ml-auto size-5" />
      </div>
      <figcaption className="px-3 pt-2 pb-3 leading-snug whitespace-pre-line">
        <span className="font-semibold">{handle(brand.name)}</span>{" "}
        <Folded
          text={caption + (arr<string>(content.hashtags).length ? "\n" : "")}
          fold={125}
          more="more"
        />
        <Hashtags tags={arr<string>(content.hashtags)} />
      </figcaption>
    </figure>
  );
}

function textOn(hex: string): string {
  const v = hex.replace("#", "");
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(v.slice(i, i + 2), 16) / 255);
  const lum = (c: number) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  const l = 0.2126 * lum(r) + 0.7152 * lum(g) + 0.0722 * lum(b);
  return 1.05 / (l + 0.05) >= (l + 0.05) / 0.05 ? "#FFFFFF" : "#000000";
}

export function CarouselPreview({ content, brand }: { content: Content; brand: Brand }) {
  const slides = arr<{ headline?: string; body?: string }>(content.slides);
  const [i, setI] = useState(0);
  const bg = /^#[0-9a-f]{6}$/i.test(brand.primary ?? "") ? (brand.primary as string) : "#1E2250";
  const fg = textOn(bg);
  const slide = slides[Math.min(i, Math.max(slides.length - 1, 0))];
  return (
    <figure className="overflow-hidden rounded-lg border bg-card text-sm">
      <div className="flex items-center gap-2 px-3 py-2">
        <Avatar brand={brand} />
        <span className="flex-1 font-semibold">{handle(brand.name)}</span>
        <span className="text-xs text-muted-foreground tabular-nums">
          {slides.length ? i + 1 : 0}/{slides.length}
        </span>
      </div>
      <div className="relative aspect-[4/5]" style={{ background: bg, color: fg }}>
        {slide && (
          <div className="flex h-full flex-col justify-center gap-3 p-8">
            <p className="font-heading text-2xl leading-tight font-semibold">{slide.headline}</p>
            <p className="text-sm leading-relaxed opacity-90">{slide.body}</p>
          </div>
        )}
        {i > 0 && (
          <Button
            size="icon-sm"
            variant="secondary"
            className="absolute top-1/2 left-2 -translate-y-1/2 rounded-full"
            onClick={() => setI(i - 1)}
            aria-label="Previous slide"
          >
            <ChevronLeft className="size-4" />
          </Button>
        )}
        {i < slides.length - 1 && (
          <Button
            size="icon-sm"
            variant="secondary"
            className="absolute top-1/2 right-2 -translate-y-1/2 rounded-full"
            onClick={() => setI(i + 1)}
            aria-label="Next slide"
          >
            <ChevronRight className="size-4" />
          </Button>
        )}
      </div>
      <div className="flex justify-center gap-1 py-2" aria-hidden>
        {slides.map((_, n) => (
          <span
            key={n}
            className={cn(
              "size-1.5 rounded-full",
              n === i ? "bg-[#0095f6]" : "bg-muted-foreground/30",
            )}
          />
        ))}
      </div>
      <figcaption className="px-3 pb-3 leading-snug whitespace-pre-line">
        <span className="font-semibold">{handle(brand.name)}</span>{" "}
        <Folded text={str(content.caption)} fold={125} more="more" />
        <Hashtags tags={arr<string>(content.hashtags)} />
      </figcaption>
    </figure>
  );
}

export function LinkedInPreview({ content, brand }: { content: Content; brand: Brand }) {
  const [device, setDevice] = useState<"desktop" | "mobile">("desktop");
  const tags = arr<string>(content.hashtags);
  const text = str(content.text) + (tags.length ? "\n\n" + tags.join(" ") : "");
  return (
    <figure className="overflow-hidden rounded-lg border bg-card text-sm">
      <div className="flex items-start gap-2 px-4 pt-3">
        <Avatar brand={brand} size="size-10" />
        <div className="min-w-0 flex-1 leading-tight">
          <p className="font-semibold">{brand.name}</p>
          <p className="flex items-center gap-1 text-xs text-muted-foreground">
            Now · <Globe2 className="size-3" aria-hidden />
          </p>
        </div>
        <ToggleGroup
          type="single"
          size="sm"
          value={device}
          onValueChange={(v) => v && setDevice(v as "desktop" | "mobile")}
          aria-label="Fold point"
        >
          <ToggleGroupItem
            value="desktop"
            aria-label="Desktop fold (210 chars)"
            className="h-6 px-1.5"
          >
            <Monitor className="size-3.5" />
          </ToggleGroupItem>
          <ToggleGroupItem
            value="mobile"
            aria-label="Mobile fold (140 chars)"
            className="h-6 px-1.5"
          >
            <Smartphone className="size-3.5" />
          </ToggleGroupItem>
        </ToggleGroup>
      </div>
      <figcaption key={device} className="px-4 py-3 leading-relaxed whitespace-pre-line">
        <Folded text={text} fold={device === "desktop" ? 210 : 140} more="see more" />
      </figcaption>
      <div
        className="flex justify-around border-t px-2 py-1.5 text-xs text-muted-foreground"
        aria-hidden
      >
        <span className="flex items-center gap-1">
          <ThumbsUp className="size-4" /> Like
        </span>
        <span className="flex items-center gap-1">
          <MessageCircle className="size-4" /> Comment
        </span>
        <span className="flex items-center gap-1">
          <Repeat2 className="size-4" /> Repost
        </span>
        <span className="flex items-center gap-1">
          <Send className="size-4" /> Send
        </span>
      </div>
    </figure>
  );
}

export function XPreview({ content, brand }: { content: Content; brand: Brand }) {
  const posts = arr<string>(content.posts);
  const tags = arr<string>(content.hashtags);
  return (
    <div className="overflow-hidden rounded-lg border bg-card text-sm">
      {posts.map((p, n) => {
        const text = p + (n === posts.length - 1 && tags.length ? " " + tags.join(" ") : "");
        const count = xWeightedLength(text);
        return (
          <div key={n} className="relative flex gap-3 px-4 py-3">
            {posts.length > 1 && n < posts.length - 1 && (
              <span className="absolute top-12 bottom-0 left-8 w-0.5 bg-border" aria-hidden />
            )}
            <Avatar brand={brand} size="size-9" />
            <div className="min-w-0 flex-1">
              <p className="leading-tight">
                <span className="font-semibold">{brand.name}</span>{" "}
                <span className="text-muted-foreground">@{handle(brand.name)}</span>
              </p>
              <p className="mt-0.5 leading-snug whitespace-pre-line">{text}</p>
              <p
                className={cn(
                  "mt-1 text-right text-xs tabular-nums",
                  count > 280 ? "font-medium text-rose" : "text-muted-foreground",
                )}
              >
                {count}/280
              </p>
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function EmailPreview({ content }: { content: Content }) {
  const subjects = arr<string>(content.subject_variants);
  const rendered = (content.rendered ?? {}) as { html?: string; text?: string };
  const [subject, setSubject] = useState(0);
  const [device, setDevice] = useState<"desktop" | "mobile">("desktop");
  const [view, setView] = useState<"html" | "text">("html");
  return (
    <div className="overflow-hidden rounded-lg border bg-card text-sm">
      <div className="space-y-2 border-b px-4 py-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-muted-foreground">Subject</span>
          <div className="flex flex-wrap gap-1">
            {subjects.map((s, n) => (
              <button
                key={n}
                type="button"
                onClick={() => setSubject(n)}
                className={cn(
                  "rounded-md border px-2 py-0.5 text-left text-xs",
                  n === subject
                    ? "border-foreground bg-accent font-medium"
                    : "text-muted-foreground",
                )}
              >
                {String.fromCharCode(65 + n)}
              </button>
            ))}
          </div>
          <div className="ml-auto flex gap-1">
            <ToggleGroup
              type="single"
              size="sm"
              value={view}
              onValueChange={(v) => v && setView(v as "html" | "text")}
              aria-label="Format"
            >
              <ToggleGroupItem value="html" className="h-6 px-2 text-xs">
                HTML
              </ToggleGroupItem>
              <ToggleGroupItem value="text" className="h-6 px-2 text-xs">
                Text
              </ToggleGroupItem>
            </ToggleGroup>
            <ToggleGroup
              type="single"
              size="sm"
              value={device}
              onValueChange={(v) => v && setDevice(v as "desktop" | "mobile")}
              aria-label="Device"
            >
              <ToggleGroupItem value="desktop" aria-label="Desktop width" className="h-6 px-1.5">
                <Monitor className="size-3.5" />
              </ToggleGroupItem>
              <ToggleGroupItem value="mobile" aria-label="Mobile width" className="h-6 px-1.5">
                <Smartphone className="size-3.5" />
              </ToggleGroupItem>
            </ToggleGroup>
          </div>
        </div>
        <p className="font-semibold">{subjects[subject]}</p>
        <p className="truncate text-xs text-muted-foreground">{str(content.preheader)}</p>
      </div>
      <div className="flex justify-center bg-muted/50 p-3">
        {view === "html" ? (
          rendered.html ? (
            <iframe
              title="Email preview"
              // No scripts, no same-origin: the email can't touch the app.
              sandbox=""
              srcDoc={rendered.html}
              className="h-[520px] rounded border bg-white transition-[width]"
              style={{ width: device === "desktop" ? 600 : 375, maxWidth: "100%" }}
            />
          ) : (
            <p className="py-10 text-muted-foreground">Preview appears once the draft is saved.</p>
          )
        ) : (
          <pre className="max-h-[520px] w-full overflow-auto rounded border bg-card p-4 text-xs whitespace-pre-wrap">
            {rendered.text}
          </pre>
        )}
      </div>
    </div>
  );
}

export function ContentPreview({
  channel,
  content,
  brand,
}: {
  channel: string;
  content: Content;
  brand: Brand;
}) {
  switch (channel) {
    case "instagram_post":
      return <InstagramPreview content={content} brand={brand} />;
    case "instagram_carousel":
      return <CarouselPreview content={content} brand={brand} />;
    case "linkedin_post":
      return <LinkedInPreview content={content} brand={brand} />;
    case "x_post":
      return <XPreview content={content} brand={brand} />;
    case "email":
      return <EmailPreview content={content} />;
    default:
      return null;
  }
}

/** Flatten structured content into comparable text (for diffs and copying). */
export function contentText(channel: string, content: Content): string {
  const tags = arr<string>(content.hashtags).join(" ");
  switch (channel) {
    case "instagram_post":
      return [str(content.caption), tags].filter(Boolean).join("\n\n");
    case "instagram_carousel":
      return [
        ...arr<{ headline?: string; body?: string }>(content.slides).map(
          (s, n) => `Slide ${n + 1}: ${s.headline}\n${s.body}`,
        ),
        str(content.caption),
        tags,
      ]
        .filter(Boolean)
        .join("\n\n");
    case "linkedin_post":
      return [str(content.text), tags].filter(Boolean).join("\n\n");
    case "x_post":
      return arr<string>(content.posts).join("\n\n") + (tags ? `\n${tags}` : "");
    case "email": {
      const sections = arr<{
        heading?: string;
        body?: string;
        items?: string[];
        button_label?: string;
      }>(content.sections);
      return [
        ...arr<string>(content.subject_variants).map(
          (s, n) => `Subject ${String.fromCharCode(65 + n)}: ${s}`,
        ),
        `Preheader: ${str(content.preheader)}`,
        ...sections.map((s) =>
          [
            s.heading,
            s.body,
            ...(s.items ?? []).map((x) => `• ${x}`),
            s.button_label && `[${s.button_label}]`,
          ]
            .filter(Boolean)
            .join("\n"),
        ),
      ].join("\n\n");
    }
    default:
      return JSON.stringify(content, null, 2);
  }
}
