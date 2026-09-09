"use client";

import Link from "next/link";
import { useState } from "react";

import { ClipList } from "@/components/ClipList";
import { RegenerateButton } from "@/components/RegenerateButton";
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
  return (
    status !== "CREATED" &&
    status !== "COMPLETED" &&
    status !== "NEEDS_REVIEW" &&
    status !== "FAILED"
  );
}

interface Props {
  project: ProjectSummary;
  onChanged: () => void;
}

export function ProjectCard({ project, onChanged }: Props) {
  const [retrying, setRetrying] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Rehacer un proyecto terminado tira lo que ya había y puede costar mucho
  // rato en un vídeo largo. Un segundo clic evita el disgusto sin sacar un
  // diálogo del navegador por delante.
  const [confirming, setConfirming] = useState(false);

  const failed = project.status === "FAILED";
  const completed = project.status === "COMPLETED";
  // El pipeline llegó al final pero la IA no propuso nada. No es un fallo: hay
  // vídeo, hay señales y hay un editor esperando.
  const needsReview = project.status === "NEEDS_REVIEW";
  // En cuanto hay vídeo descargado se puede recortar a mano, aunque el resto
  // del pipeline todavía esté en marcha o haya fallado después.
  const editable = project.status !== "CREATED" && project.status !== "DOWNLOADING";

  async function reprocess() {
    setRetrying(true);
    setError(null);
    try {
      await retryProject(project.id);
      setConfirming(false);
      setExpanded(false);
      onChanged();
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : "No se ha podido reprocesar");
    } finally {
      setRetrying(false);
    }
  }

  function handleReprocessClick() {
    // Un fallo no tiene nada que perder; un proyecto terminado sí.
    if (completed && !confirming) {
      setConfirming(true);
      return;
    }
    void reprocess();
  }

  const reprocessButton = (
    <RegenerateButton
      label={failed || needsReview ? "Reintentar" : "Regenerar"}
      confirming={confirming}
      busy={retrying}
      onClick={handleReprocessClick}
      onBlur={() => setConfirming(false)}
      title={
        completed
          ? "Vuelve a pasar el vídeo entero por el pipeline y sustituye los clips automáticos"
          : undefined
      }
    />
  );

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
            <span
              className={
                failed ? "text-rose-400" : needsReview ? "text-amber-400" : undefined
              }
            >
              {PROJECT_STATUS_LABELS[project.status]}
              {isRunning(project.status) && "…"}
            </span>
            <span aria-hidden="true">·</span>
            <span>{formatDuration(project.duration)}</span>
          </p>
          {(failed || needsReview) && project.error_message && (
            <p
              className={`mt-1 truncate text-xs ${
                failed ? "text-rose-400/80" : "text-amber-400/80"
              }`}
              title={project.error_message}
            >
              {project.error_message}
            </p>
          )}
          {error && <p className="mt-1 text-xs text-rose-400">{error}</p>}
        </div>

        {editable && (
          <Link
            href={`/projects/${project.id}`}
            className={`shrink-0 rounded-lg px-3 py-1.5 text-xs transition ${
              needsReview
                ? "bg-amber-500/90 font-medium text-amber-950 hover:bg-amber-400"
                : "border border-white/10 text-zinc-300 hover:border-white/20 hover:text-zinc-100"
            }`}
          >
            {needsReview ? "Recortar a mano" : "Abrir editor"}
          </Link>
        )}

        {completed && (
          <button
            type="button"
            onClick={() => setExpanded((value) => !value)}
            aria-expanded={expanded}
            className="shrink-0 rounded-lg border border-white/10 px-3 py-1.5 text-xs text-zinc-300 transition hover:border-white/20 hover:text-zinc-100"
          >
            {expanded ? "Ocultar clips" : "Ver clips"}
          </button>
        )}

        {(failed || completed || needsReview) && reprocessButton}
      </div>

      {/* Se monta solo al desplegar: así no se piden los clips de cada
          proyecto de la lista sin que nadie los haya mirado. */}
      {completed && expanded && (
        <ClipList projectId={project.id} emptyAction={reprocessButton} />
      )}
    </li>
  );
}
