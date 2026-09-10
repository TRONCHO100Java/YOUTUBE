"use client";

import Link from "next/link";
import { type ReactNode, useCallback, useEffect, useState } from "react";

import { PublishButton } from "@/components/PublishButton";
import { PublishingNotes } from "@/components/PublishingNotes";
import {
  clipSubtitlesUrl,
  clipVideoUrl,
  deleteClipFile,
  listClips,
  markClipUploaded,
} from "@/lib/api";
import type { GeneratedClip } from "@/lib/types";

function formatTime(seconds: number): string {
  const total = Math.round(seconds);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

function formatSize(bytes: number | null): string {
  if (bytes === null) return "—";
  return `${(bytes / 1_048_576).toFixed(1)} MB`;
}

/** Verde para lo bueno, ámbar para lo dudoso: se lee de un vistazo. */
function scoreTone(score: number): string {
  if (score >= 80) return "text-emerald-400";
  if (score >= 60) return "text-amber-400";
  return "text-zinc-400";
}

interface Props {
  projectId: string;
  /** Botón de regenerar del proyecto, para no dejar el estado vacío sin salida. */
  emptyAction?: ReactNode;
  /**
   * Cambiarlo obliga a releer los clips.
   *
   * Los clips no cambian solos, así que no se hace polling; pero sí cambian
   * cuando algo de fuera los toca —retitular, por ejemplo— y entonces lo que
   * hay pintado es de antes.
   */
  reloadKey?: number;
}

export function ClipList({ projectId, emptyAction, reloadKey = 0 }: Props) {
  const [clips, setClips] = useState<GeneratedClip[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Por clip y no global: si se marca uno mientras se borra otro, cada botón
  // tiene que saber si le toca a él.
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(() => {
    listClips(projectId)
      .then(setClips)
      .catch((cause: unknown) => {
        setError(cause instanceof Error ? cause.message : "Error desconocido");
      });
  }, [projectId]);

  useEffect(() => {
    load();
  }, [load, reloadKey]);

  /**
   * Aplica un cambio a un clip y sustituye solo ese, sin releer la lista.
   *
   * Releer entera devolvería el mismo resultado a costa de repintar doce
   * reproductores de vídeo, y el usuario vería parpadear la página por haber
   * pulsado un botón en una tarjeta.
   */
  async function act(
    clipId: string,
    action: () => Promise<GeneratedClip>,
  ): Promise<void> {
    if (busyId !== null) return;

    setBusyId(clipId);
    setError(null);
    try {
      const updated = await action();
      setClips(
        (current) =>
          current?.map((clip) => (clip.id === updated.id ? updated : clip)) ?? null,
      );
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : "No se ha podido");
    } finally {
      setBusyId(null);
    }
  }

  // Solo se traga la lista si no hay nada que enseñar. Un fallo al marcar un
  // clip no puede hacer desaparecer los otros once.
  if (error !== null && clips === null) {
    return <p className="px-4 pb-4 text-sm text-rose-400">{error}</p>;
  }

  if (clips === null) {
    return <p className="px-4 pb-4 text-sm text-zinc-500">Cargando clips…</p>;
  }

  // Un proyecto puede tener momentos detectados y ningún clip generado: se
  // analizó con una versión anterior, o los candidatos salieron de las señales
  // y están esperando a que alguien decida. El editor es donde se resuelve.
  if (clips.length === 0) {
    return (
      <div className="flex flex-wrap items-center gap-3 px-4 pb-4">
        <p className="text-sm text-zinc-500">
          Este proyecto no tiene clips generados todavía.
        </p>
        <Link
          href={`/projects/${projectId}`}
          className="rounded-lg border border-white/10 px-3 py-1.5 text-xs text-zinc-300 transition hover:border-white/20 hover:text-zinc-100"
        >
          Abrir editor
        </Link>
        {emptyAction}
      </div>
    );
  }

  return (
    <>
      {error !== null && (
        <p role="alert" className="px-4 pb-2 text-sm text-rose-400">
          {error}
        </p>
      )}

    <ol className="grid gap-3 px-3 pb-3 sm:grid-cols-2">
      {clips.map((clip, index) => {
        const gone = clip.deleted_at !== null;
        const uploaded = clip.published_at !== null;
        const busy = busyId === clip.id;

        return (
        <li
          key={clip.id}
          className={`overflow-hidden rounded-lg border border-white/5 bg-black/20 ${
            gone ? "opacity-60" : ""
          }`}
        >
          {/* Sin fichero no hay reproductor: un <video> roto haría pensar que
              el clip falló, cuando lo que pasó es que se liberó sitio. */}
          {gone ? (
            <div className="flex aspect-[9/16] w-full flex-col items-center justify-center gap-1 bg-black/40 px-4 text-center">
              <p className="text-sm text-zinc-500">Fichero borrado</p>
              <p className="text-xs text-zinc-600">
                La ficha se conserva: título, nota y vistas siguen aquí.
              </p>
            </div>
          ) : (
            <video
              src={clipVideoUrl(clip.id)}
              controls
              preload="metadata"
              className="aspect-[9/16] w-full bg-black"
            />
          )}

          <div className="p-3">
            <div className="flex items-baseline gap-2">
              <span className="text-xs text-zinc-600">
                #{clip.rank ?? index + 1}
              </span>
              <span
                className={`text-lg font-semibold tabular-nums ${scoreTone(clip.score)}`}
              >
                {Math.round(clip.score)}
                <span className="text-xs font-normal text-zinc-600">/100</span>
              </span>
              {uploaded && (
                <span className="rounded bg-emerald-500/15 px-1.5 py-0.5 text-[11px] text-emerald-400">
                  Subido
                </span>
              )}
            </div>

            <p className="mt-1 text-sm text-zinc-100">{clip.title}</p>

            {clip.hook && (
              <p className="mt-2 border-l-2 border-emerald-500/40 pl-3 text-xs italic text-zinc-400">
                {clip.hook}
              </p>
            )}

            <PublishingNotes
              title={clip.title}
              description={clip.description}
              hashtags={clip.hashtags}
            />

            <p className="mt-2 text-[11px] tabular-nums text-zinc-600">
              {clip.width}×{clip.height} · {Math.round(clip.duration ?? 0)}s ·{" "}
              {formatSize(clip.filesize_bytes)} · {clip.encoder}
              {clip.has_burned_subtitles && " · subtítulos incrustados"}
            </p>
            <p className="text-[11px] tabular-nums text-zinc-600">
              Del original {formatTime(clip.start_time)} –{" "}
              {formatTime(clip.end_time)}
            </p>

            {!gone && (
              <div className="mt-3 flex flex-wrap gap-2">
                {/* Enlaces normales: el navegador descarga sin pasar por JS. */}
                <a
                  href={clipVideoUrl(clip.id)}
                  download
                  className="rounded-lg bg-emerald-500 px-3 py-1.5 text-xs font-medium text-zinc-950 transition hover:bg-emerald-400"
                >
                  Descargar MP4
                </a>
                {clip.has_subtitle_file && (
                  <a
                    href={clipSubtitlesUrl(clip.id)}
                    download
                    className="rounded-lg border border-white/10 px-3 py-1.5 text-xs text-zinc-300 transition hover:border-white/20 hover:text-zinc-100"
                  >
                    .srt
                  </a>
                )}

                {/* Subir a mano por Studio es una vía legítima, y hoy la única
                    que publica en público sin pasar la auditoría de Google. Sin
                    este botón el sistema no se entera y el clip volvería a la
                    carpeta del canal en cada exportación. */}
                {!uploaded && (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void act(clip.id, () => markClipUploaded(clip.id))}
                    className="rounded-lg border border-white/10 px-3 py-1.5 text-xs text-zinc-300 transition hover:border-emerald-400/40 hover:text-emerald-300 disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    {busy ? "Marcando…" : "Marcar subido"}
                  </button>
                )}

                {/* Solo cuando ya está subido: borrar el único sitio donde
                    existe el vídeo antes de publicarlo sería tirar el trabajo. */}
                {uploaded && (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void act(clip.id, () => deleteClipFile(clip.id))}
                    className="rounded-lg border border-white/10 px-3 py-1.5 text-xs text-zinc-500 transition hover:border-rose-500/40 hover:text-rose-400 disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    {busy
                      ? "Borrando…"
                      : `Borrar fichero · ${formatSize(clip.filesize_bytes)}`}
                  </button>
                )}
              </div>
            )}

            {!gone && !uploaded && (
              <div className="mt-2">
                <PublishButton clip={clip} onPublished={load} />
              </div>
            )}
          </div>
        </li>
        );
      })}
    </ol>
    </>
  );
}
