"use client";

import Link from "next/link";
import { useState } from "react";

import { ClipList } from "@/components/ClipList";
import { RegenerateButton } from "@/components/RegenerateButton";
import { retitleProject, retryProject, waitForTask } from "@/lib/api";
import {
  isProjectRunning,
  PROJECT_STATUS_LABELS,
  type ProjectSummary,
} from "@/lib/types";

function formatDuration(seconds: number | null): string {
  if (seconds === null) return "—";
  const minutes = Math.floor(seconds / 60);
  const rest = Math.round(seconds % 60);
  return `${minutes}:${String(rest).padStart(2, "0")}`;
}

interface Props {
  project: ProjectSummary;
  onChanged: () => void;
  /**
   * Hay otro proyecto pasando por el pipeline. El worker procesa un vídeo
   * cada vez, así que esto es lo que separa "hay alguien delante" de
   * "esto no lo ha cogido nadie", que piden cosas distintas al usuario.
   */
  workerBusy?: boolean;
}

export function ProjectCard({ project, onChanged, workerBusy = false }: Props) {
  const [retrying, setRetrying] = useState(false);
  const [retitling, setRetitling] = useState(false);
  // Qué ha pasado con el último retitulado. Un botón que encola trabajo y no
  // dice nada más se lee como un botón roto: la petición va bien, pero el
  // trabajo tarda unos segundos y por la pantalla no pasa nada.
  const [retitled, setRetitled] = useState<string | null>(null);
  // Cambiarlo obliga a la lista de clips a releer: los títulos nuevos están
  // en la base de datos, pero lo que hay pintado es de antes.
  const [clipsKey, setClipsKey] = useState(0);
  const [expanded, setExpanded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Rehacer un proyecto terminado tira lo que ya había y puede costar mucho
  // rato en un vídeo largo. Un segundo clic evita el disgusto sin sacar un
  // diálogo del navegador por delante.
  const [confirming, setConfirming] = useState(false);

  const failed = project.status === "FAILED";
  const completed = project.status === "COMPLETED";
  // Encolado: la tarea está escrita en Redis y nadie la ha cogido todavía.
  // Es un estado de espera legítimo, pero hasta ahora dejaba la tarjeta sin
  // un solo botón, y un proyecto sin botones parece un proyecto roto.
  const queued = project.status === "CREATED";
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

  async function retitle() {
    setRetitling(true);
    setRetitled(null);
    setError(null);
    try {
      const { task_id } = await retitleProject(project.id);
      const finished = await waitForTask(task_id);

      if (finished === null) {
        setRetitled("Está tardando más de lo normal. Sigue en marcha.");
      } else if (finished.successful) {
        const count = Number(finished.result?.retitled ?? 0);
        setRetitled(
          count > 0
            ? `${count} ${count === 1 ? "título reescrito" : "títulos reescritos"}`
            // Sin afirmar por qué: "seguían siendo los mejores" sería una
            // certeza que aquí no se tiene. Puede que el modelo no haya
            // propuesto nada distinto, o nada en absoluto.
            : "Sin cambios en los títulos",
        );
        // Los clips que hay pintados llevan el título viejo.
        setClipsKey((value) => value + 1);
        onChanged();
      } else {
        setError(finished.error ?? "No se han podido reescribir los títulos");
      }
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : "No se han podido reescribir");
    } finally {
      setRetitling(false);
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
      label={queued ? "Reencolar" : failed || needsReview ? "Reintentar" : "Regenerar"}
      confirming={confirming}
      busy={retrying}
      onClick={handleReprocessClick}
      onBlur={() => setConfirming(false)}
      title={
        completed
          ? "Vuelve a pasar el vídeo entero por el pipeline y sustituye los clips automáticos"
          : queued
            ? "Vuelve a pedir turno. Úsalo solo si el worker se cayó con el proyecto en cola"
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
              {isProjectRunning(project.status) && "…"}
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
          {queued && (
            <p className="mt-1 text-xs text-zinc-500">
              {workerBusy
                ? "Esperando turno: el worker está procesando otro proyecto y solo puede con uno a la vez."
                : "Encolado. Si no arranca en unos segundos, comprueba que la ventana del worker siga abierta y pulsa Reencolar."}
            </p>
          )}
          {retitling && (
            <p className="mt-1 text-xs text-zinc-500">
              Reescribiendo los títulos con la IA. Tarda unos segundos.
            </p>
          )}
          {retitled && !retitling && (
            <p className="mt-1 text-xs text-emerald-400/80">{retitled}</p>
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

        {/* Reescribir títulos no vuelve a renderizar: el título no está dentro
            del MP4. Cuesta segundos, así que va separado del botón que sí
            reprocesa el vídeo entero. */}
        {(completed || needsReview) && (
          <button
            type="button"
            disabled={retitling}
            onClick={() => void retitle()}
            title="Vuelve a escribir los títulos con la IA. No re-renderiza nada"
            className="shrink-0 rounded-lg border border-white/10 px-3 py-1.5 text-xs text-zinc-300 transition hover:border-white/20 hover:text-zinc-100 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {retitling ? "Reescribiendo…" : "Retitular"}
          </button>
        )}

        {(failed || completed || needsReview || queued) && reprocessButton}
      </div>

      {/* Se monta solo al desplegar: así no se piden los clips de cada
          proyecto de la lista sin que nadie los haya mirado. */}
      {completed && expanded && (
        <ClipList projectId={project.id} reloadKey={clipsKey} emptyAction={reprocessButton} />
      )}
    </li>
  );
}
