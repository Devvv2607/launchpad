import { AlertTriangle } from "lucide-react";

import { Button } from "@/components/ui/button";
import { describeError, toErrorInfo } from "@/lib/errors";
import { cn } from "@/lib/utils";

/** Human-readable AI error with a concrete fix hint. Never blank, never generic. */
export function AIErrorState({
  error,
  onRetry,
  className,
}: {
  error: unknown;
  onRetry?: () => void;
  className?: string;
}) {
  const info = toErrorInfo(error);
  if (info.code === "aborted") return null;
  const { title, detail, hint } = describeError(info);
  return (
    <div
      role="alert"
      className={cn(
        "flex items-start gap-3 rounded-lg border border-rose/30 bg-rose-soft p-4 text-sm",
        className,
      )}
    >
      <AlertTriangle className="mt-0.5 size-4 shrink-0 text-rose" aria-hidden />
      <div className="min-w-0 flex-1 space-y-1">
        <p className="font-medium">{title}</p>
        <p className="text-foreground/80">{detail}</p>
        {hint && <p className="text-foreground/80">{hint}</p>}
        {(info.model || info.requestId) && (
          <p className="text-xs text-muted-foreground">
            {info.model && (
              <>
                {info.provider} · <code>{info.model}</code>
              </>
            )}
            {info.model && info.requestId && " · "}
            {info.requestId && (
              <>
                Request ID <code className="select-all">{info.requestId}</code>
              </>
            )}
          </p>
        )}
      </div>
      {onRetry && info.code !== "spend_cap_exceeded" && info.code !== "llm_auth" && (
        <Button size="sm" variant="outline" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
}
