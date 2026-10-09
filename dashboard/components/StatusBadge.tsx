import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { statusBadge, commitmentBadge } from "@/lib/domainConfig";

// One pill for every status vocabulary in the app. Lead statuses and
// commitment states keep their colours in lib/domainConfig.ts; process-agent
// and execution statuses are free strings, so they're mapped to a tone here.
export type Tone = "ok" | "warn" | "bad" | "info" | "muted";

const TONE_CLASSES: Record<Tone, string> = {
  ok: "bg-ok/10 text-ok border-ok/20",
  warn: "bg-warn/10 text-warn border-warn/20",
  bad: "bg-bad/10 text-bad border-bad/20",
  info: "bg-primary/10 text-primary border-primary/20",
  muted: "bg-muted text-muted-foreground border-border",
};

export function ToneBadge({
  tone,
  children,
  dot = false,
  className,
}: {
  tone: Tone;
  children: React.ReactNode;
  dot?: boolean;
  className?: string;
}) {
  return (
    <Badge variant="outline" className={cn("capitalize", TONE_CLASSES[tone], className)}>
      {dot && <span className="w-1.5 h-1.5 rounded-full bg-current" />}
      {children}
    </Badge>
  );
}

export function StatusBadge({ status }: { status: string }) {
  const b = statusBadge(status);
  return (
    <Badge variant="outline" className={cn("border-transparent", b.cls)}>
      {b.label}
    </Badge>
  );
}

export function CommitmentBadge({ state }: { state: string }) {
  const b = commitmentBadge(state);
  return (
    <Badge variant="outline" className={cn("border-transparent", b.cls)}>
      {b.label}
    </Badge>
  );
}

export function ActiveBadge({ active }: { active: boolean }) {
  return (
    <ToneBadge tone={active ? "ok" : "muted"} dot>
      {active ? "Active" : "Inactive"}
    </ToneBadge>
  );
}

export function processStatusTone(status: string): Tone {
  const s = status.toLowerCase();
  if (s === "active" || s === "published" || s === "live") return "ok";
  if (s === "draft") return "warn";
  if (s === "archived" || s === "disabled" || s === "paused") return "bad";
  return "muted";
}

export function ProcessStatusBadge({ status }: { status: string }) {
  return <ToneBadge tone={processStatusTone(status)}>{status}</ToneBadge>;
}

export function executionStatusTone(status: string): Tone {
  const s = status.toLowerCase();
  if (s === "completed" || s === "connected" || s === "booked") return "ok";
  if (s === "calling" || s === "dispatching" || s === "retry_pending" || s === "retry_scheduled") return "warn";
  if (s === "callback_scheduled" || s === "pending") return "info";
  if (s === "failed" || s === "suppressed_dnc") return "bad";
  return "muted";
}

export function ExecutionStatusBadge({ status }: { status: string }) {
  return <ToneBadge tone={executionStatusTone(status)}>{status.replace(/_/g, " ")}</ToneBadge>;
}
