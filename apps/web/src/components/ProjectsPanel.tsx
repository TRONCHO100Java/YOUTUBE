"use client";

import { useCallback } from "react";

import { NewProjectForm } from "@/components/NewProjectForm";
import { ProjectCard } from "@/components/ProjectCard";
import { usePolling } from "@/hooks/usePolling";
import { listProjects } from "@/lib/api";
import { POLL_INTERVAL_MS } from "@/lib/config";
import type { Page, ProjectSummary } from "@/lib/types";

/**
 * Formulario de creación y lista de proyectos.
 *
 * Ambos comparten el mismo `refresh` para que un proyecto recién creado
 * aparezca al instante en lugar de esperar al siguiente ciclo de polling.
 */
export function ProjectsPanel() {
  const fetcher = useCallback(() => listProjects(), []);
  const { data, error, loading, refresh } = usePolling<Page<ProjectSummary>>(
    fetcher,
    POLL_INTERVAL_MS,
  );
  const projects = data?.items;

  return (
    <>
      <NewProjectForm onCreated={refresh} />

      <section aria-label="Proyectos" className="mt-10">
        <h2 className="text-sm font-medium text-zinc-400">Proyectos</h2>

        {error && (
          <p role="alert" className="mt-3 text-sm text-rose-400">
            {error}
          </p>
        )}

        {!error && !loading && projects?.length === 0 && (
          <p className="mt-3 rounded-xl border border-dashed border-white/10 px-4 py-8 text-center text-sm text-zinc-500">
            Todavía no hay proyectos. Pega una URL de YouTube para empezar.
          </p>
        )}

        {projects && projects.length > 0 && (
          <ul className="mt-3 space-y-2">
            {projects.map((project) => (
              <ProjectCard key={project.id} project={project} onChanged={refresh} />
            ))}
          </ul>
        )}
      </section>
    </>
  );
}
