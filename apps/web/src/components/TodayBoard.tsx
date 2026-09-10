"use client";

import { useCallback, useMemo, useState } from "react";

import { CopyButton } from "@/components/CopyButton";
import { usePolling } from "@/hooks/usePolling";
import {
  clipThumbnailUrl,
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
  if (score >= 80) return "bg-emerald-500/15 text-emerald-400";
  if (score >= 60) return "bg-amber-500/15 text-amber-400";
  return "bg-white/5 text-zinc-400";
}

type SortKey = "score" | "duration" | "project";

const SORTS: { key: SortKey; label: string; hint: string }[] = [
  { key: "score", label: "Nota", hint: "Lo mejor primero: si solo subes tres, que sean estos" },
  { key: "duration", label: "Duración", hint: "Los cortos rinden distinto que los de dos minutos" },
  { key: "project", label: "Vídeo", hint: "Juntos los del mismo vídeo, para no repetir tema seguido" },
];

function sortClips(clips: RoutedClip[], key: SortKey): RoutedClip[] {
  const sorted = [...clips];
  if (key === "score") return sorted.sort((a, b) => b.score - a.score);
  if (key === "duration") return sorted.sort((a, b) => (a.duration ?? 0) - (b.duration ?? 0));
  return sorted.sort(
    (a, b) =>
      (a.project_title ?? "").localeCompare(b.project_title ?? "") || b.score - a.score,
  );
}

/**
 * La pantalla del día: qué hay listo para subir, agrupado por canal.
 *
 * Es la única que se abre a diario, y por eso está separada de la
 * configuración. Los clips salen agrupados por canal —que es como se suben— y
 * no por proyecto, que es como se procesan.
 *
 * Los canales vacíos se resumen en una línea en vez de ocupar una ficha cada
 * uno: con diez canales y dos con trabajo, ocho fichas vacías eran ocho
 * pantallas de nada entre medias. Pero se siguen nombrando, porque saber que
 * Speed lleva días a cero es justo lo que dice que hay que echarle vídeos.
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
  const [sort, setSort] = useState<SortKey>("score");
  const [collapsed, setCollapsed] = useState(false);

  const groups = useMemo(() => {
    if (!routing || !channels) return [];
    return channels
      .map((channel) => ({
        channel,
        clips: sortClips(
          routing.filter((clip) => clip.channel_id === channel.id),
          sort,
        ),
      }))
      .sort((a, b) => b.clips.length - a.clips.length);
  }, [routing, channels, sort]);

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

  const withWork = groups.filter((group) => group.clips.length > 0);
  const empty = groups.filter((group) => group.clips.length === 0);
  const orphans = routing.filter((clip) => !clip.channel_id);
  const total = routing.length - orphans.length;

  return (
    <section aria-label="Listo para subir">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <button
          type="button"
          onClick={() => setCollapsed((value) => !value)}
          aria-expanded={!collapsed}
          className="group flex items-center gap-2 text-sm font-medium text-zinc-300 transition hover:text-zinc-100"
        >
          <span
            aria-hidden
            className={`text-xs text-zinc-600 transition-transform ${collapsed ? "" : "rotate-90"}`}
          >
            ▶
          </span>
          Listo para subir
          <span className="rounded-full bg-emerald-500/15 px-2 py-0.5 text-[11px] tabular-nums text-emerald-400">
            {total}
          </span>
        </button>

        <span className="text-xs text-zinc-600">
          en {withWork.length} {withWork.length === 1 ? "canal" : "canales"}
        </span>

        {!collapsed && total > 0 && (
          <div className="ml-auto flex items-center gap-1">
            <span className="mr-1 text-[11px] text-zinc-600">Ordenar</span>
            {SORTS.map((option) => (
              <button
                key={option.key}
                type="button"
                title={option.hint}
                onClick={() => setSort(option.key)}
                className={`rounded-lg px-2.5 py-1 text-[11px] transition ${
                  sort === option.key
                    ? "bg-white/10 text-zinc-100"
                    : "text-zinc-500 hover:text-zinc-300"
                }`}
              >
                {option.label}
              </button>
            ))}
          </div>
        )}
      </div>

      {actionError && (
        <p role="alert" className="mt-2 text-sm text-rose-400">
          {actionError}
        </p>
      )}

      {!collapsed && (
        <>
          {total === 0 && (
            <p className="mt-3 rounded-xl border border-dashed border-white/10 px-4 py-6 text-center text-sm text-zinc-500">
              Nada pendiente. Echa vídeos a la cola o revisa los canales vigilados.
            </p>
          )}

          <div className="mt-3 space-y-3">
            {withWork.map(({ channel, clips }) => (
              <details
                key={channel.id}
                open
                className="overflow-hidden rounded-xl border border-white/10 bg-white/[0.02]"
              >
                <summary className="flex cursor-pointer select-none items-center gap-3 px-4 py-3 hover:bg-white/[0.02]">
                  <span className="text-sm font-medium text-zinc-100">{channel.name}</span>
                  <span className="rounded-full bg-emerald-500/15 px-2 py-0.5 text-[11px] tabular-nums text-emerald-400">
                    {clips.length}
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

                <ul className="grid gap-px bg-white/5 sm:grid-cols-2">
                  {clips.map((clip) => (
                    <li key={clip.clip_id} className="flex gap-3 bg-[#0b0b0d] p-3">
                      {/* Miniatura y no <video>: pintar veinte reproductores de
                          treinta megas para ver el primer fotograma de cada uno
                          era lo que dejaba la lista en negro. */}
                      <a
                        href={clipVideoUrl(clip.clip_id)}
                        target="_blank"
                        rel="noreferrer"
                        title="Abrir el clip"
                        className="group relative h-[124px] w-[70px] shrink-0 overflow-hidden rounded bg-black"
                      >
                        {/* Sin `loading="lazy"` a propósito. Esta lista se
                            repinta cada pocos segundos por el sondeo, y el
                            cargador diferido de Chrome no llegaba a
                            dispararse nunca: medido, cero de treinta y tres
                            imágenes pedidas, y las treinta y tres al
                            quitarlo. Diferir tampoco ganaba nada aquí: son
                            26 KB cada una y el navegador las cachea. */}
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img
                          src={clipThumbnailUrl(clip.clip_id)}
                          alt=""
                          className="h-full w-full object-cover transition group-hover:opacity-70"
                        />
                        <span className="absolute inset-0 flex items-center justify-center text-lg text-white/0 transition group-hover:text-white/90">
                          ▶
                        </span>
                        <span className="absolute bottom-0 right-0 bg-black/70 px-1 text-[10px] tabular-nums text-zinc-300">
                          {Math.round(clip.duration ?? 0)}s
                        </span>
                      </a>

                      <div className="min-w-0 flex-1">
                        <div className="flex items-start gap-2">
                          <span
                            className={`shrink-0 rounded px-1.5 py-0.5 text-[11px] font-semibold tabular-nums ${scoreTone(clip.score)}`}
                          >
                            {Math.round(clip.score)}
                          </span>
                          <p className="min-w-0 flex-1 text-sm leading-snug text-zinc-100">
                            {clip.title}
                          </p>
                        </div>

                        <p className="mt-1 truncate text-[11px] text-zinc-600">
                          {clip.project_title}
                        </p>
                        <p className="mt-0.5 line-clamp-1 text-[11px] text-sky-400/60">
                          {clip.hashtags.map((tag) => `#${tag}`).join(" ")}
                        </p>

                        <div className="mt-2 flex flex-wrap gap-1.5">
                          <CopyButton value={publishText(clip)} label="Copiar texto" />
                          <a
                            href={clipVideoUrl(clip.clip_id)}
                            download
                            className="rounded-lg bg-emerald-500 px-2.5 py-1 text-[11px] font-medium text-zinc-950 transition hover:bg-emerald-400"
                          >
                            Descargar
                          </a>
                          <button
                            type="button"
                            disabled={busyId === clip.clip_id}
                            onClick={() =>
                              void act(clip.clip_id, () => markClipUploaded(clip.clip_id))
                            }
                            className="rounded-lg border border-white/10 px-2.5 py-1 text-[11px] text-zinc-400 transition hover:border-emerald-400/40 hover:text-emerald-300 disabled:opacity-40"
                          >
                            {busyId === clip.clip_id ? "…" : "Subido"}
                          </button>
                        </div>
                      </div>
                    </li>
                  ))}
                </ul>
              </details>
            ))}
          </div>

          {empty.length > 0 && (
            <p className="mt-3 text-[11px] text-zinc-600">
              Sin clips: {empty.map((group) => group.channel.name).join(" · ")}
            </p>
          )}

          {/* Los huérfanos son la señal más útil: dicen qué línea editorial falta. */}
          {orphans.length > 0 && (
            <p className="mt-2 text-xs text-amber-400/80">
              {orphans.length} {orphans.length === 1 ? "clip no encaja" : "clips no encajan"} en
              ningún canal. Si se repite una clase que nadie acepta, falta un canal para ella.
            </p>
          )}
        </>
      )}
    </section>
  );
}
