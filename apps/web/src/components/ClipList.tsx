"use client";

import Link from "next/link";
import { type ReactNode, useEffect, useState } from "react";

import { clipSubtitlesUrl, clipVideoUrl, listClips } from "@/lib/api";
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
}

export function ClipList({ projectId, emptyAction }: Props) {
  const [clips, setClips] = useState<GeneratedClip[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    listClips(projectId)
      .then((result) => {
        if (!cancelled) setClips(result);
      })
      .catch((cause: unknown) => {
        if (!cancelled) {
          setError(
            cause instanceof Error ? cause.message : "Error desconocido",
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  if (error) {
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
    <ol className="grid gap-3 px-3 pb-3 sm:grid-cols-2">
      {clips.map((clip, index) => (
        <li
          key={clip.id}
          className="overflow-hidden rounded-lg border border-white/5 bg-black/20"
        >
          <video
            src={clipVideoUrl(clip.id)}
            controls
            preload="metadata"
            className="aspect-[9/16] w-full bg-black"
          />

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
            </div>

            <p className="mt-1 text-sm text-zinc-100">{clip.title}</p>

            {clip.hook && (
              <p className="mt-2 border-l-2 border-emerald-500/40 pl-3 text-xs italic text-zinc-400">
                {clip.hook}
              </p>
            )}

            <p className="mt-2 text-[11px] tabular-nums text-zinc-600">
              {clip.width}×{clip.height} · {Math.round(clip.duration ?? 0)}s ·{" "}
              {formatSize(clip.filesize_bytes)} · {clip.encoder}
              {clip.has_burned_subtitles && " · subtítulos incrustados"}
            </p>
            <p className="text-[11px] tabular-nums text-zinc-600">
              Del original {formatTime(clip.start_time)} –{" "}
              {formatTime(clip.end_time)}
            </p>

            <div className="mt-3 flex gap-2">
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
            </div>
          </div>
        </li>
      ))}
    </ol>
  );
}
