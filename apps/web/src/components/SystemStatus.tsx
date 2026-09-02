"use client";

import { StatusDot } from "@/components/StatusDot";
import { usePolling } from "@/hooks/usePolling";
import { getReadiness } from "@/lib/api";
import { API_BASE_URL, POLL_INTERVAL_MS } from "@/lib/config";
import type { HealthStatus, Readiness } from "@/lib/types";

const COMPONENT_LABELS: Record<string, string> = {
  database: "PostgreSQL",
  redis: "Redis",
  worker: "Worker Celery",
};

const OVERALL_LABELS: Record<HealthStatus, string> = {
  ok: "Todos los servicios operativos",
  degraded: "Operativo con incidencias",
  error: "Servicios no disponibles",
};

/** Panel de estado de la API y sus dependencias. */
export function SystemStatus() {
  const { data: readiness, error, loading } = usePolling<Readiness>(getReadiness, POLL_INTERVAL_MS);

  const overall: HealthStatus = error ? "error" : (readiness?.status ?? "degraded");

  return (
    <section
      aria-label="Estado del sistema"
      className="rounded-xl border border-white/10 bg-white/[0.03] p-5"
    >
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <StatusDot status={overall} pulse={loading} />
          <h2 className="text-sm font-medium text-zinc-100">
            {loading ? "Comprobando API…" : (error ?? OVERALL_LABELS[overall])}
          </h2>
        </div>
        <code className="text-xs text-zinc-500">{API_BASE_URL}</code>
      </header>

      {readiness && (
        <>
          <dl className="mt-4 grid gap-2 sm:grid-cols-3">
            {Object.entries(readiness.components).map(([key, component]) => (
              <div
                key={key}
                className="flex items-center gap-2 rounded-lg border border-white/5 bg-black/20 px-3 py-2"
                title={component.detail ?? undefined}
              >
                <StatusDot status={component.status} />
                <dt className="text-sm text-zinc-300">{COMPONENT_LABELS[key] ?? key}</dt>
                <dd className="ml-auto text-xs text-zinc-500">{component.status}</dd>
              </div>
            ))}
          </dl>
          <p className="mt-3 text-xs text-zinc-500">
            {readiness.app} v{readiness.version} · entorno {readiness.environment}
          </p>
        </>
      )}
    </section>
  );
}
