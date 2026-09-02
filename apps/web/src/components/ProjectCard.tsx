"use client";

import { useState } from "react";

import { CandidateList } from "@/components/CandidateList";
import { retryProject } from "@/lib/api";
import { PROJECT_STATUS_LABELS, type ProjectSummary } from "@/lib/types";

function formatDuration(seconds: number | null): string {
  if (seconds === null) return "—";
  const minutes = Math.floor(seconds / 60);
  const rest = Math.round(seconds % 60);
  return `${minutes}:${String(rest).padStart(2, "0")}`;
}

/** Los estados intermedios son los que justifican seguir haciendo polling. */
function isRunning(status: ProjectSummary["status"]): boolean {
  return status !== "CREATED" && status !== "COMPLETED" && status !== "FAILED";
}

interface Props {
  project: ProjectSummary;
  onChanged: () => void;
}

export function ProjectCard({ project, onChanged }: Props) {
  const [retrying, setRetrying] = useState(false);
  const [expanded, setExpanded] = useState(false);

  const failed = project.status === "FAILED";
  const completed = project.status === "COMPLETED";

  async function handleRetry() {
    setRetrying(true);
    try {
      await retryProject(project.id);
      onChanged();
    } finally {
      setRetrying(false);
    }
  }

  return (
    <li className="rounded-xl border border-white/10 bg-white/[0.03]">
      <div className="flex items-center gap-4 p-3">
        <div className="h-14 w-24 shrink-0 overflow-hidden rounded-lg bg-black/40">
          {project.thumbnail_url && (
            // Miniatura remota de YouTube: <img> evita configurar dominios en next/image.
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={project.thumbnail_url}
              alt=""
              className="h-full w-full object-cover"
              loading="lazy"
            />
          )}
        </div>

        <div className="min-w-0 flex-1">
          <p className="truncate text-sm text-zinc-100">
            {project.title ?? project.source_url ?? project.id}
          </p>
          <p className="mt-0.5 flex items-center gap-2 text-xs text-zinc-500">
            <span className={failed ? "text-rose-400" : undefined}>
              {PROJECT_STATUS_LABELS[project.status]}
              {isRunning(project.status) && "…"}
            </span>
            <span aria-hidden="true">·</span>
            <span>{formatDuration(project.duration)}</span>
          </p>
          {failed && project.error_message && (
            <p className="mt-1 truncate text-xs text-rose-400/80" title={project.error_message}>
              {project.error_message}
            </p>
          )}
        </div>

        {completed && (
          <button
            type="button"
            onClick={() => setExpanded((value) => !value)}
            aria-expanded={expanded}
            className="shrink-0 rounded-lg border border-white/10 px-3 py-1.5 text-xs text-zinc-300 transition hover:border-white/20 hover:text-zinc-100"
          >
            {expanded ? "Ocultar momentos" : "Ver momentos"}
          </button>
        )}

        {failed && (
          <button
            type="button"
            onClick={() => void handleRetry()}
            disabled={retrying}
            className="shrink-0 rounded-lg border border-white/10 px-3 py-1.5 text-xs text-zinc-300 transition hover:border-white/20 hover:text-zinc-100 disabled:opacity-50"
          >
            {retrying ? "Reintentando…" : "Reintentar"}
          </button>
        )}
      </div>

      {/* Se monta solo al desplegar: así no se piden los candidatos de cada
          proyecto de la lista sin que nadie los haya mirado. */}
      {completed && expanded && <CandidateList projectId={project.id} />}
    </li>
  );
}
