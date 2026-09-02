import type { HealthStatus } from "@/lib/types";

const TONE: Record<HealthStatus, string> = {
  ok: "bg-emerald-400",
  degraded: "bg-amber-400",
  error: "bg-rose-500",
};

export function StatusDot({ status, pulse = false }: { status: HealthStatus; pulse?: boolean }) {
  return (
    <span className="relative inline-flex size-2.5 shrink-0" aria-hidden="true">
      {pulse && (
        <span
          className={`absolute inline-flex size-full animate-ping rounded-full opacity-60 ${TONE[status]}`}
        />
      )}
      <span className={`relative inline-flex size-2.5 rounded-full ${TONE[status]}`} />
    </span>
  );
}
