"use client";

import { ImageUp, Loader2 } from "lucide-react";
import { useRef, useState } from "react";

import { ErrorState } from "@/components/states";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { Schemas } from "@/lib/api/client";
import { useUploadLogo } from "@/lib/api/hooks";
import { cn } from "@/lib/utils";

type Palette = Schemas["PaletteColorOut"][];
export type ColorRole = "primary_color" | "secondary_color" | "accent";

const RATING_STYLE: Record<string, string> = {
  AAA: "bg-leaf-soft text-leaf",
  AA: "bg-leaf-soft text-leaf",
  "AA large": "bg-marigold-soft text-foreground",
  fail: "bg-rose-soft text-rose",
};

export function LogoPanel({
  workspaceId,
  logoUrl,
  palette,
  hasColors,
  onApply,
  onApplyAll,
}: {
  workspaceId: string;
  logoUrl: string | null | undefined;
  palette: Palette;
  hasColors: boolean;
  onApply: (role: ColorRole, hex: string) => void;
  onApplyAll: (palette: Palette) => void;
}) {
  const upload = useUploadLogo(workspaceId);
  const input = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [confirm, setConfirm] = useState(false);

  function pick(files: FileList | null) {
    const file = files?.[0];
    if (file) upload.mutate(file);
  }

  return (
    <div className="space-y-5">
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          pick(e.dataTransfer.files);
        }}
        className={cn(
          "flex flex-wrap items-center gap-5 rounded-lg border border-dashed bg-card p-5 transition-colors",
          dragging && "border-ring bg-accent",
        )}
      >
        <div className="grid size-24 shrink-0 place-items-center overflow-hidden rounded-md border bg-[repeating-conic-gradient(var(--muted)_0%_25%,transparent_0%_50%)] bg-[length:16px_16px]">
          {logoUrl ? (
            // eslint-disable-next-line @next/next/no-img-element -- signed, short-lived URL
            <img src={logoUrl} alt="Your logo" className="max-h-20 max-w-20 object-contain" />
          ) : (
            <ImageUp className="size-7 text-muted-foreground" aria-hidden />
          )}
        </div>
        <div className="min-w-0 flex-1">
          <p className="font-medium">{logoUrl ? "Replace your logo" : "Upload your logo"}</p>
          <p className="mt-1 text-sm text-muted-foreground">
            PNG with a transparent background works best. JPEG, WebP or GIF up to 5 MB.
          </p>
        </div>
        <input
          ref={input}
          type="file"
          accept="image/png,image/jpeg,image/webp,image/gif"
          className="sr-only"
          aria-label="Logo file"
          onChange={(e) => {
            pick(e.target.files);
            e.target.value = "";
          }}
        />
        <Button
          variant="outline"
          onClick={() => input.current?.click()}
          disabled={upload.isPending}
        >
          {upload.isPending ? (
            <>
              <Loader2 className="size-4 animate-spin" aria-hidden /> Uploading…
            </>
          ) : (
            "Choose file"
          )}
        </Button>
      </div>

      {upload.error && <ErrorState error={upload.error} />}

      {palette.length > 0 && (
        <div className="space-y-3">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <p className="font-medium">Colours from your logo</p>
              <p className="text-sm text-muted-foreground">
                Suggestions only. Contrast shows how readable text is on each colour.
              </p>
            </div>
            <Button size="sm" onClick={() => (hasColors ? setConfirm(true) : onApplyAll(palette))}>
              Use suggested colours
            </Button>
          </div>
          <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {palette.map((c) => (
              <li key={c.hex} className="flex gap-3 rounded-lg border bg-card p-3">
                <span
                  className="size-12 shrink-0 rounded-md ring-1 ring-foreground/15"
                  style={{ background: c.hex }}
                  aria-hidden
                />
                <div className="min-w-0 flex-1 space-y-1.5">
                  <div className="flex items-center gap-2">
                    <code className="text-sm font-medium">{c.hex}</code>
                    <span className="text-xs text-muted-foreground capitalize">{c.role}</span>
                  </div>
                  <div className="flex flex-wrap gap-1 text-xs">
                    <Badge variant="outline" className={RATING_STYLE[c.rating_on_white]}>
                      on white {c.contrast_white}:1 {c.rating_on_white}
                    </Badge>
                    <Badge variant="outline" className={RATING_STYLE[c.rating_on_black]}>
                      on black {c.contrast_black}:1 {c.rating_on_black}
                    </Badge>
                  </div>
                  <div className="flex flex-wrap gap-1">
                    {(
                      [
                        ["primary_color", "Primary"],
                        ["secondary_color", "Secondary"],
                        ["accent", "Accent"],
                      ] as const
                    ).map(([role, label]) => (
                      <Button
                        key={role}
                        size="xs"
                        variant="outline"
                        onClick={() => onApply(role, c.hex)}
                      >
                        {label}
                      </Button>
                    ))}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

      <AlertDialog open={confirm} onOpenChange={setConfirm}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Replace your current colours?</AlertDialogTitle>
            <AlertDialogDescription>
              Your brand kit already has colours. This fills the form with the logo&apos;s primary,
              secondary and accent suggestions. Nothing is saved until you press Save.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep my colours</AlertDialogCancel>
            <AlertDialogAction onClick={() => onApplyAll(palette)}>
              Use suggestions
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
