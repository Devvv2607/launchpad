import { cn } from "@/lib/utils";

/** Wordmark: a marigold spark rising off a baseline — the "launch". */
export function Logo({ className }: { className?: string }) {
  return (
    <span
      className={cn("inline-flex items-center gap-2 font-heading text-lg font-semibold", className)}
    >
      <svg viewBox="0 0 24 24" className="size-6" aria-hidden>
        <path d="M3 20h18" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
        <path d="M12 16V4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
        <path
          d="M7.5 8.5 12 4l4.5 4.5"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <circle cx="18" cy="5" r="2.2" fill="var(--marigold)" />
      </svg>
      Launchpad
    </span>
  );
}
