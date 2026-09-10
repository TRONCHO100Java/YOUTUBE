"use client";

import { useCallback } from "react";

import { ChannelsPanel } from "@/components/ChannelsPanel";
import { Collapsible } from "@/components/Collapsible";
import { NewProjectForm } from "@/components/NewProjectForm";
import { ProjectCard } from "@/components/ProjectCard";
import { PublishChannelsPanel } from "@/components/PublishChannelsPanel";
import { VideoSearch } from "@/components/VideoSearch";
import { usePolling } from "@/hooks/usePolling";
import { listProjects } from "@/lib/api";
import { POLL_INTERVAL_MS } from "@/lib/config";
import { isProjectRunning, type Page, type ProjectSummary } from "@/lib/types";

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
  // El worker procesa un vídeo cada vez. Si alguno está en marcha, los que
  // figuran en cola no están parados: están esperando su turno.
  const workerBusy = projects?.some((project) => isProjectRunning(project.status)) ?? false;

  return (
    <>
      <NewProjectForm onCreated={refresh} />

      {/* Todo lo de abajo es configuración: se toca al montar un canal y
          luego casi nunca. Va plegado para no tener que recorrer media
          página de formularios cada vez que se entra a subir clips. */}
      <Collapsible title="Buscar vídeos en YouTube">
        <VideoSearch onQueued={refresh} />
      </Collapsible>

      <Collapsible title="Canales vigilados">
        <ChannelsPanel />
      </Collapsible>

      <Collapsible title="Canales de publicación">
        <PublishChannelsPanel />
      </Collapsible>

      <Collapsible
        title="Proyectos"
        defaultOpen
        badge={
          projects ? (
            <span className="rounded-full bg-white/5 px-2 py-0.5 text-[11px] tabular-nums text-zinc-500">
              {projects.length}
            </span>
          ) : null
        }
      >

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
              <ProjectCard
                key={project.id}
                project={project}
                onChanged={refresh}
                workerBusy={workerBusy}
              />
            ))}
          </ul>
        )}
      </Collapsible>
    </>
  );
}
