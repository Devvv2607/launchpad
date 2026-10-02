import { AlertTriangle } from "lucide-react";

import { Button } from "@/components/ui/button";
import { describeError, toErrorInfo } from "@/lib/errors";
import { cn } from "@/lib/utils";

// Retrying can't fix these; the message tells the user what to change instead.
const NOT_RETRYABLE = new Set([
  "spend_cap_exceeded",
  "llm_auth",
  "llm_not_configured",
  "llm_model_not_found",
]);

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
      {onRetry && !NOT_RETRYABLE.has(info.code) && (
        <Button size="sm" variant="outline" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
}
