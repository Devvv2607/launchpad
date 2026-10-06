"use client";

import {
  Bot,
  ChevronsUpDown,
  LayoutDashboard,
  LogOut,
  Menu,
  Monitor,
  Moon,
  Palette,
  Plus,
  SlidersHorizontal,
  Sparkles,
  Sun,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTheme } from "next-themes";
import { useEffect, useState } from "react";

import { Logo } from "@/components/logo";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { useLogout, useMe, useWorkspaces } from "@/lib/api/hooks";
import { INDUSTRY_LABELS } from "@/lib/labels";
import { cn } from "@/lib/utils";
import { rememberWorkspace } from "@/lib/workspace";

function navFor(wsId: string) {
  return [
    { href: `/w/${wsId}`, label: "Dashboard", icon: LayoutDashboard, exact: true },
    { href: `/w/${wsId}/agent`, label: "Agent", icon: Bot },
    { href: `/w/${wsId}/create`, label: "Create", icon: Sparkles },
    { href: `/w/${wsId}/brand`, label: "Brand kit", icon: Palette },
    { href: `/w/${wsId}/settings/ai`, label: "AI settings", icon: SlidersHorizontal },
  ];
}

export function AppShell({
  workspaceId,
  children,
}: {
  workspaceId: string;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    rememberWorkspace(workspaceId);
  }, [workspaceId]);

  return (
    <div className="min-h-dvh lg:grid lg:grid-cols-[16rem_minmax(0,1fr)]">
      <aside className="hidden bg-sidebar text-sidebar-foreground lg:block">
        <div className="sticky top-0 flex h-dvh flex-col">
          <Sidebar workspaceId={workspaceId} />
        </div>
      </aside>
      <div className="flex min-w-0 flex-col">
        <header className="flex items-center gap-3 border-b bg-card px-4 py-3 lg:hidden">
          <Sheet open={open} onOpenChange={setOpen}>
            <SheetTrigger className="rounded-md p-2 hover:bg-muted" aria-label="Open navigation">
              <Menu className="size-5" />
            </SheetTrigger>
            <SheetContent
              side="left"
              className="w-72 border-0 bg-sidebar p-0 text-sidebar-foreground"
            >
              <SheetTitle className="sr-only">Navigation</SheetTitle>
              <Sidebar workspaceId={workspaceId} onNavigate={() => setOpen(false)} />
            </SheetContent>
          </Sheet>
          <Logo />
        </header>
        <main className="flex-1 px-4 py-6 sm:px-8 sm:py-8">{children}</main>
      </div>
    </div>
  );
}

function Sidebar({ workspaceId, onNavigate }: { workspaceId: string; onNavigate?: () => void }) {
  const pathname = usePathname();
  return (
    <>
      <div className="px-5 pt-5 pb-4 text-white">
        <Logo />
      </div>
      <div className="px-3">
        <WorkspaceSwitcher workspaceId={workspaceId} />
      </div>
      <nav className="mt-4 flex-1 space-y-0.5 px-3" aria-label="Workspace">
        {navFor(workspaceId).map((item) => {
          const active = item.exact ? pathname === item.href : pathname.startsWith(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={active ? "page" : undefined}
              onClick={onNavigate}
              className={cn(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors hover:bg-sidebar-accent hover:text-white focus-visible:ring-2 focus-visible:ring-sidebar-ring focus-visible:outline-none",
                active && "bg-sidebar-accent font-medium text-white",
              )}
            >
              <item.icon className="size-4" aria-hidden />
              {item.label}
            </Link>
          );
        })}
      </nav>
      <div className="border-t border-sidebar-border p-3">
        <UserMenu />
      </div>
    </>
  );
}

function WorkspaceSwitcher({ workspaceId }: { workspaceId: string }) {
  const { data, isLoading } = useWorkspaces();
  const current = data?.find((w) => w.id === workspaceId);
  if (isLoading) return <Skeleton className="h-12 w-full bg-sidebar-accent" />;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger className="flex w-full items-center gap-3 rounded-md bg-sidebar-accent px-3 py-2 text-left hover:bg-sidebar-accent/80 focus-visible:ring-2 focus-visible:ring-sidebar-ring focus-visible:outline-none">
        <span className="grid size-8 shrink-0 place-items-center rounded bg-sidebar-primary font-heading font-semibold text-sidebar-primary-foreground">
          {current?.name.charAt(0).toUpperCase() ?? "?"}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium text-white">
            {current?.name ?? "Workspace"}
          </span>
          {current && (
            <span className="block truncate text-xs text-sidebar-foreground/70">
              {INDUSTRY_LABELS[current.industry].label}
            </span>
          )}
        </span>
        <ChevronsUpDown className="size-4 shrink-0 opacity-60" aria-hidden />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-60">
        <DropdownMenuLabel>Workspaces</DropdownMenuLabel>
        {data?.map((w) => (
          <DropdownMenuItem key={w.id} asChild>
            <Link href={`/w/${w.id}`} className={cn(w.id === workspaceId && "font-medium")}>
              {w.name}
            </Link>
          </DropdownMenuItem>
        ))}
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild>
          <Link href="/onboarding">
            <Plus className="size-4" aria-hidden /> New workspace
          </Link>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function UserMenu() {
  const me = useMe();
  const logout = useLogout();
  const { theme, setTheme } = useTheme();
  const initials = (me.data?.name ?? me.data?.email ?? "?")
    .split(/[\s@]/)
    .filter(Boolean)
    .slice(0, 2)
    .map((s) => s[0]?.toUpperCase())
    .join("");
  return (
    <DropdownMenu>
      <DropdownMenuTrigger className="flex w-full items-center gap-3 rounded-md px-2 py-2 text-left hover:bg-sidebar-accent focus-visible:ring-2 focus-visible:ring-sidebar-ring focus-visible:outline-none">
        <Avatar className="size-8">
          <AvatarFallback className="bg-sidebar-accent text-xs text-white">
            {initials}
          </AvatarFallback>
        </Avatar>
        <span className="min-w-0 flex-1 truncate text-sm">
          {me.data?.name ?? me.data?.email ?? "…"}
        </span>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" side="top" className="w-60">
        <DropdownMenuLabel className="truncate font-normal text-muted-foreground">
          {me.data?.email}
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuLabel>Theme</DropdownMenuLabel>
        <DropdownMenuRadioGroup value={theme} onValueChange={setTheme}>
          <DropdownMenuRadioItem value="light">
            <Sun className="size-4" aria-hidden /> Light
          </DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="dark">
            <Moon className="size-4" aria-hidden /> Dark
          </DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="system">
            <Monitor className="size-4" aria-hidden /> System
          </DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => logout.mutate()}>
          <LogOut className="size-4" aria-hidden /> Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
