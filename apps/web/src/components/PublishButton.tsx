"use client";

import { useState } from "react";

import { publishClip, waitForTask } from "@/lib/api";
import type { GeneratedClip } from "@/lib/types";

interface Props {
  clip: GeneratedClip;
  /** Se invoca al terminar para que la lista relea el clip ya publicado. */
  onPublished: () => void;
}

/**
 * Sube el clip a YouTube y espera a que termine.
 *
 * Espera de verdad —no encola y calla— porque una subida tarda y un botón que
 * responde al instante sin que pase nada visible se lee como un botón roto.
 *
 * Cuando el clip ya está subido deja de ser un botón y pasa a ser el enlace a
 * su vídeo, con su privacidad al lado. Eso último no es un detalle: un
 * proyecto de API sin auditar sube **siempre en privado**, y creer que algo
 * está publicado cuando no lo está es peor que no haberlo subido.
 */
export function PublishButton({ clip, onPublished }: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (clip.youtube_video_id) {
    return (
      <div className="flex flex-wrap items-center gap-2">
        <a
          href={`https://www.youtube.com/shorts/${clip.youtube_video_id}`}
          target="_blank"
          rel="noreferrer"
          className="rounded-lg border border-white/10 px-3 py-1.5 text-xs text-zinc-300 transition hover:border-white/20 hover:text-zinc-100"
        >
          Ver en YouTube
        </a>
        {clip.privacy_status && clip.privacy_status !== "public" && (
          <span
            className="rounded border border-amber-500/30 bg-amber-500/10 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-amber-300"
            title="Un proyecto de API sin auditar sube siempre en privado. Publícalo desde YouTube."
          >
            {clip.privacy_status === "private" ? "privado" : clip.privacy_status}
          </span>
        )}
        {clip.view_count !== null && (
          <span className="text-[11px] tabular-nums text-zinc-500">
            {clip.view_count.toLocaleString("es-ES")} vistas
          </span>
        )}
      </div>
    );
  }

  async function publish() {
    setBusy(true);
    setError(null);
    try {
      const { task_id } = await publishClip(clip.id);
      const finished = await waitForTask(task_id, { intervalMs: 3000, timeoutMs: 600_000 });

      if (finished === null) {
        setError("La subida está tardando. Sigue en marcha.");
      } else if (finished.successful) {
        onPublished();
      } else {
        setError(finished.error ?? "No se ha podido subir");
      }
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : "No se ha podido subir");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <button
        type="button"
        disabled={busy}
        onClick={() => void publish()}
        title="Sube el MP4 con su título, descripción y etiquetas ya puestos"
        className="rounded-lg border border-white/10 px-3 py-1.5 text-xs text-zinc-300 transition hover:border-white/25 hover:text-zinc-100 disabled:cursor-not-allowed disabled:opacity-40"
      >
        {busy ? "Subiendo…" : "Subir a YouTube"}
      </button>
      {error && <span className="text-[11px] text-rose-400">{error}</span>}
    </div>
  );
}
