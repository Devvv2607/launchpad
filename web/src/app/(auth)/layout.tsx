import { Logo } from "@/components/logo";

const WEEK = [
  { day: "Mon", item: "Monsoon menu teaser", state: "published" },
  { day: "Tue", item: "Barista reel script", state: "approved" },
  { day: "Wed", item: "Ganesh Chaturthi poster", state: "review" },
  { day: "Thu", item: "Loyalty email", state: "review" },
  { day: "Fri", item: "Weekend brunch carousel", state: "draft" },
] as const;

const STATE_STYLE = {
  published: "bg-leaf",
  approved: "bg-leaf/60",
  review: "bg-marigold",
  draft: "bg-sidebar-foreground/30",
} as const;

export default function AuthLayout({ children }: LayoutProps<"/">) {
  return (
    <div className="grid min-h-dvh lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
      <main className="flex flex-col px-6 py-8 sm:px-12">
        <Logo />
        <div className="flex flex-1 items-center">
          <div className="w-full max-w-sm">{children}</div>
        </div>
      </main>
      <aside
        aria-hidden
        className="relative hidden overflow-hidden bg-sidebar px-12 py-16 text-sidebar-foreground lg:flex lg:flex-col lg:justify-center"
      >
        <h2 className="max-w-md text-4xl leading-tight font-semibold text-white">
          Your week of marketing, planned by an agent and signed off by you.
        </h2>
        <p className="mt-4 max-w-md text-sidebar-foreground/80">
          Nothing goes out until you approve it. Marigold means it&apos;s waiting on you.
        </p>
        <ol className="mt-10 max-w-md space-y-2">
          {WEEK.map((w) => (
            <li
              key={w.day}
              className="flex items-center gap-4 rounded-md bg-sidebar-accent/70 px-4 py-3"
            >
              <span className="w-9 text-sm text-sidebar-foreground/60">{w.day}</span>
              <span className="flex-1 text-sm text-white">{w.item}</span>
              <span className={`size-2.5 rounded-full ${STATE_STYLE[w.state]}`} />
            </li>
          ))}
        </ol>
      </aside>
    </div>
  );
}
