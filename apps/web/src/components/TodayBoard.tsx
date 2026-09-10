"use client";

import { useCallback, useState } from "react";

import { CopyButton } from "@/components/CopyButton";
import { usePolling } from "@/hooks/usePolling";
import {
  clipVideoUrl,
  listPublishChannels,
  listRouting,
  markClipUploaded,
} from "@/lib/api";
import { POLL_INTERVAL_MS } from "@/lib/config";
import type { PublishChannel, RoutedClip } from "@/lib/types";

/** Lo que se pega en la caja de YouTube: título, descripción y etiquetas. */
function publishText(clip: RoutedClip): string {
  return [clip.title, "", clip.description ?? "", "", clip.hashtags.map((t) => `#${t}`).join(" ")]
    .join("\n")
    .trim();
}

function scoreTone(score: number): string {
  if (score >= 80) return "text-emerald-400";
  if (score >= 60) return "text-amber-400";
  return "text-zinc-400";
}

/**
 * La pantalla del día: qué hay listo para subir, agrupado por canal.
 *
 * Es la única que se abre a diario, y por eso está separada de la
 * configuración. Antes, para saber qué subir había que bajar por el buscador,
 * los canales vigilados y los diez canales de destino hasta llegar a los
 * proyectos, y aun así los clips estaban repartidos por proyecto —que es como
 * se procesan— y no por canal, que es como se suben.
 *
 * Un canal con cero clips también sale: saber que Speed lleva dos días vacío
 * es justo lo que dice que hay que echarle vídeos.
 */
export function TodayBoard() {
  const routingFetcher = useCallback(() => listRouting(), []);
  const channelsFetcher = useCallback(() => listPublishChannels(), []);

  const { data: routing, error, refresh } = usePolling<RoutedClip[]>(
    routingFetcher,
    POLL_INTERVAL_MS,
  );
  const { data: channels } = usePolling<PublishChannel[]>(channelsFetcher, POLL_INTERVAL_MS);

  const [busyId, setBusyId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  async function act(clipId: string, action: () => Promise<unknown>): Promise<void> {
    if (busyId !== null) return;
    setBusyId(clipId);
    setActionError(null);
    try {
      await action();
      refresh();
    } catch (cause: unknown) {
      setActionError(cause instanceof Error ? cause.message : "No se ha podido");
    } finally {
      setBusyId(null);
    }
  }

  if (error !== null && routing === null) {
    return <p className="text-sm text-rose-400">{error}</p>;
  }
  if (routing === null || channels === null) {
    return <p className="text-sm text-zinc-500">Cargando…</p>;
  }

  const orphans = routing.filter((clip) => !clip.channel_id);
  const byChannel = channels
    .map((channel) => ({
      channel,
      clips: routing.filter((clip) => clip.channel_id === channel.id),
    }))
    // Los que tienen trabajo primero: es la lista de tareas del día.
    .sort((a, b) => b.clips.length - a.clips.length);

  const total = routing.length - orphans.length;

  return (
    <section aria-label="Listo para subir">
      <div className="flex items-baseline justify-between">
        <h2 className="text-sm font-medium text-zinc-400">Listo para subir</h2>
        <p className="text-xs text-zinc-500">
          {total} {total === 1 ? "clip" : "clips"} en {byChannel.filter((g) => g.clips.length).length}{" "}
          canales
        </p>
      </div>

      {actionError && (
        <p role="alert" className="mt-2 text-sm text-rose-400">
          {actionError}
        </p>
      )}

      {total === 0 && (
        <p className="mt-3 rounded-xl border border-dashed border-white/10 px-4 py-6 text-center text-sm text-zinc-500">
          Nada pendiente. Echa vídeos a la cola o revisa los canales vigilados.
        </p>
      )}

      <div className="mt-3 space-y-3">
        {byChannel.map(({ channel, clips }) => (
          <details
            key={channel.id}
            open={clips.length > 0}
            className="overflow-hidden rounded-xl border border-white/10 bg-white/[0.02]"
          >
            <summary className="flex cursor-pointer items-center gap-3 px-4 py-3">
              <span className="text-sm text-zinc-100">{channel.name}</span>
              <span
                className={
                  clips.length > 0
                    ? "rounded bg-emerald-500/15 px-1.5 py-0.5 text-[11px] text-emerald-400"
                    : "text-[11px] text-zinc-600"
                }
              >
                {clips.length} {clips.length === 1 ? "clip" : "clips"}
              </span>
              {!channel.has_outro && (
                <span
                  className="text-[11px] text-amber-400/70"
                  title="Sus clips saldrán sin el cierre con el nombre del canal"
                >
                  sin cierre
                </span>
              )}
            </summary>

            {clips.length > 0 && (
              <ul className="divide-y divide-white/5 border-t border-white/5">
                {clips.map((clip) => (
                  <li key={clip.clip_id} className="flex flex-wrap items-start gap-3 px-4 py-3">
                    <video
                      src={clipVideoUrl(clip.clip_id)}
                      controls
                      preload="none"
                      className="h-40 w-[90px] shrink-0 rounded bg-black"
                    />

                    <div className="min-w-0 flex-1">
                      <p className="flex items-baseline gap-2">
                        <span className={`text-sm font-semibold tabular-nums ${scoreTone(clip.score)}`}>
                          {Math.round(clip.score)}
                        </span>
                        <span className="min-w-0 flex-1 truncate text-sm text-zinc-100">
                          {clip.title}
                        </span>
                      </p>
                      <p className="mt-0.5 truncate text-[11px] text-zinc-600">
                        {Math.round(clip.duration ?? 0)}s · {clip.project_title}
                      </p>
                      <p className="mt-1 truncate text-[11px] text-sky-400/70">
                        {clip.hashtags.map((tag) => `#${tag}`).join(" ")}
                      </p>

                      <div className="mt-2 flex flex-wrap gap-2">
                        <CopyButton value={publishText(clip)} label="Copiar para YouTube" />
                        <a
                          href={clipVideoUrl(clip.clip_id)}
                          download
                          className="rounded-lg bg-emerald-500 px-3 py-1.5 text-xs font-medium text-zinc-950 transition hover:bg-emerald-400"
                        >
                          Descargar
                        </a>
                        <button
                          type="button"
                          disabled={busyId === clip.clip_id}
                          onClick={() =>
                            void act(clip.clip_id, () => markClipUploaded(clip.clip_id))
                          }
                          className="rounded-lg border border-white/10 px-3 py-1.5 text-xs text-zinc-300 transition hover:border-emerald-400/40 hover:text-emerald-300 disabled:opacity-40"
                        >
                          {busyId === clip.clip_id ? "…" : "Marcar subido"}
                        </button>
                        {/* Borrar sin haberlo subido tiraría el trabajo, así que
                            aquí no está: aparece en la ficha del clip una vez
                            marcado, que es cuando deja de hacer falta. */}
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </details>
        ))}
      </div>

      {/* Los huérfanos son la señal más útil: dicen qué línea editorial falta. */}
      {orphans.length > 0 && (
        <p className="mt-3 text-xs text-amber-400/80">
          {orphans.length} {orphans.length === 1 ? "clip no encaja" : "clips no encajan"} en ningún
          canal. Mira sus etiquetas: si se repite una clase que nadie acepta, falta un canal para
          ella.
        </p>
      )}
    </section>
  );
}
