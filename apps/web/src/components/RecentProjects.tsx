"use client";

import { useCallback } from "react";

import { usePolling } from "@/hooks/usePolling";
import { listProjects } from "@/lib/api";
import { POLL_INTERVAL_MS } from "@/lib/config";
import { PROJECT_STATUS_LABELS, type Page, type ProjectSummary } from "@/lib/types";

function formatDuration(seconds: number | null): string {
  if (seconds === null) return "—";
  const minutes = Math.floor(seconds / 60);
  const rest = Math.round(seconds % 60);
  return `${minutes}:${String(rest).padStart(2, "0")}`;
}

export function RecentProjects() {
  const fetcher = useCallback(() => listProjects(), []);
  const { data, error } = usePolling<Page<ProjectSummary>>(fetcher, POLL_INTERVAL_MS);
  const projects = data?.items;

  return (
    <section aria-label="Proyectos recientes" className="mt-8">
      <h2 className="text-sm font-medium text-zinc-400">Proyectos recientes</h2>

      {error && <p className="mt-3 text-sm text-rose-400">{error}</p>}

      {!error && projects?.length === 0 && (
        <p className="mt-3 rounded-xl border border-dashed border-white/10 px-4 py-8 text-center text-sm text-zinc-500">
          Todavía no hay proyectos. El formulario para pegar una URL de YouTube llega en la FASE 2.
        </p>
      )}

      {projects && projects.length > 0 && (
        <ul className="mt-3 space-y-2">
          {projects.map((project) => (
            <li
              key={project.id}
              className="flex items-center justify-between gap-4 rounded-xl border border-white/10 bg-white/[0.03] px-4 py-3"
            >
              <div className="min-w-0">
                <p className="truncate text-sm text-zinc-100">
                  {project.title ?? project.source_url ?? project.id}
                </p>
                <p className="text-xs text-zinc-500">
                  {PROJECT_STATUS_LABELS[project.status]} · {formatDuration(project.duration)}
                </p>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
