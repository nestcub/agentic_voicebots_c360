import { statusBadge, commitmentBadge } from "@/lib/domainConfig";

export function StatusBadge({ status }: { status: string }) {
  const b = statusBadge(status);
  return <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${b.cls}`}>{b.label}</span>;
}

export function CommitmentBadge({ state }: { state: string }) {
  const b = commitmentBadge(state);
  return <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${b.cls}`}>{b.label}</span>;
}
