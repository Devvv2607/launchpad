import { AlertTriangle, type LucideIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api/client";
import { cn } from "@/lib/utils";

/** Shows the real error from the API, including the request id to quote in bug reports. */
export function ErrorState({
  error,
  onRetry,
  className,
}: {
  error: unknown;
  onRetry?: () => void;
  className?: string;
}) {
  const fields = error instanceof ApiError ? Object.entries(error.fieldErrors()) : [];
  const message =
    fields.length > 0
      ? fields.map(([k, v]) => `${k.replace(/_/g, " ")}: ${v}`).join(" · ")
      : error instanceof Error
        ? error.message
        : "Something went wrong.";
  const requestId = error instanceof ApiError ? error.requestId : undefined;
  return (
    <div
      role="alert"
      className={cn(
        "flex items-start gap-3 rounded-lg border border-rose/30 bg-rose-soft p-4 text-sm",
        className,
      )}
    >
      <AlertTriangle className="mt-0.5 size-4 shrink-0 text-rose" aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="font-medium">{message}</p>
        {requestId && (
          <p className="mt-1 text-xs text-muted-foreground">
            Request ID <code className="select-all">{requestId}</code>
          </p>
        )}
      </div>
      {onRetry && (
        <Button size="sm" variant="outline" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
}

export function EmptyState({
  icon: Icon,
  title,
  children,
  action,
  className,
}: {
  icon: LucideIcon;
  title: string;
  children?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col items-start gap-3 py-2", className)}>
      <span className="grid size-9 place-items-center rounded-md bg-muted text-muted-foreground">
        <Icon className="size-4" aria-hidden />
      </span>
      <div>
        <p className="font-medium">{title}</p>
        {children && <p className="mt-1 max-w-prose text-sm text-muted-foreground">{children}</p>}
      </div>
      {action}
    </div>
  );
}

export function ListSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="space-y-2" aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className="h-10 w-full" />
      ))}
    </div>
  );
}
