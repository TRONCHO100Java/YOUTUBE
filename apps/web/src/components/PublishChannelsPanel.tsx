"use client";

import { useCallback, useState, type FormEvent } from "react";

import { usePolling } from "@/hooks/usePolling";
import {
  buildChannelOutro,
  createPublishChannel,
  deletePublishChannel,
  listPublishChannels,
  listRouting,
  updatePublishChannel,
} from "@/lib/api";
import { POLL_INTERVAL_MS } from "@/lib/config";
import type { PublishChannel, RoutedClip } from "@/lib/types";

/** Se escribe separado por comas; se guarda como lista. */
function toList(raw: string): string[] {
  return raw
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean);
}

/**
 * Canales propios donde se publican los clips.
 *
 * No confundir con los canales vigilados, que son de donde SALEN los vídeos.
 * Este es el otro extremo del flujo.
 *
 * Existe porque un canal de Shorts funciona cuando lo que publica se parece
 * entre sí. Con varios a la vez —uno de Speed, otro de Among Us— hay que
 * decidir qué clip va a cuál, y hacerlo a mano cinco veces por vídeo no
 * escala. Aquí se declara qué quiere cada canal y el reparto sale solo de las
 * etiquetas que ya lleva cada clip.
 */
export function PublishChannelsPanel() {
  const channelsFetcher = useCallback(() => listPublishChannels(), []);
  const routingFetcher = useCallback(() => listRouting(), []);

  const { data: channels, error, refresh } = usePolling<PublishChannel[]>(
    channelsFetcher,
    POLL_INTERVAL_MS,
  );
  const { data: routing, refresh: refreshRouting } = usePolling<RoutedClip[]>(
    routingFetcher,
    POLL_INTERVAL_MS,
  );

  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [people, setPeople] = useState("");
  const [niche, setNiche] = useState("");
  const [kinds, setKinds] = useState("");
  const [minScore, setMinScore] = useState("");
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  // Por canal: generar un cierre tarda unos segundos y hay que saber a
  // cuál de los diez se le está haciendo.
  const [buildingId, setBuildingId] = useState<string | null>(null);
  const [handles, setHandles] = useState<Record<string, string>>({});

  async function handleAdd(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    // La URL no se exige: la línea editorial se decide antes de que el canal
    // exista en YouTube, y se puede empezar a apartarle clips desde ya.
    if (busy || name.trim().length === 0) return;

    setBusy(true);
    setFormError(null);
    try {
      await createPublishChannel({
        name: name.trim(),
        url: url.trim(),
        niche,
        people: toList(people),
        kinds: toList(kinds),
        minScore: minScore ? Number(minScore) : 0,
      });
      setName("");
      setUrl("");
      setPeople("");
      setNiche("");
      setKinds("");
      setMinScore("");
      refresh();
      refreshRouting();
    } catch (cause: unknown) {
      setFormError(cause instanceof Error ? cause.message : "No se ha podido añadir");
    } finally {
      setBusy(false);
    }
  }

  async function act(action: () => Promise<unknown>): Promise<void> {
    setFormError(null);
    try {
      await action();
      refresh();
      refreshRouting();
    } catch (cause: unknown) {
      setFormError(cause instanceof Error ? cause.message : "No se ha podido");
    }
  }

  const pending = routing?.filter((clip) => !clip.youtube_video_id) ?? [];
  const orphans = pending.filter((clip) => !clip.channel_id);

  return (
    <section aria-label="Canales de publicación" className="mt-10">
      <h2 className="text-sm font-medium text-zinc-400">Canales de publicación</h2>
      <p className="mt-1 text-xs text-zinc-500">
        Dónde acaba cada clip. El reparto sale de las etiquetas que ya lleva: quién sale,
        de qué va y qué clase de momento es.
      </p>

      <form onSubmit={handleAdd} className="mt-3 space-y-3">
        <div className="flex flex-col gap-3 sm:flex-row">
          <input
            type="text"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Nombre del canal (Speed Clips)"
            aria-label="Nombre del canal"
            className="min-w-0 flex-1 rounded-xl border border-white/10 bg-white/[0.03] px-4 py-2.5 text-sm text-zinc-100 placeholder:text-zinc-600 focus:border-emerald-400/50 focus:outline-none focus:ring-1 focus:ring-emerald-400/30"
          />
          <input
            type="text"
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            placeholder="URL del canal (puedes dejarla para luego)"
            aria-label="URL del canal"
            className="min-w-0 flex-1 rounded-xl border border-white/10 bg-white/[0.03] px-4 py-2.5 text-sm text-zinc-100 placeholder:text-zinc-600 focus:border-emerald-400/50 focus:outline-none focus:ring-1 focus:ring-emerald-400/30"
          />
        </div>

        <div className="flex flex-col gap-3 sm:flex-row">
          <input
            type="text"
            value={people}
            onChange={(event) => setPeople(event.target.value)}
            placeholder="Quién sale: speed, kai cenat"
            aria-label="Personas que acepta"
            title="Basta con que el clip mencione a una. Vacío = cualquiera"
            className="min-w-0 flex-1 rounded-xl border border-white/10 bg-white/[0.03] px-4 py-2.5 text-sm text-zinc-100 placeholder:text-zinc-600 focus:border-emerald-400/50 focus:outline-none focus:ring-1 focus:ring-emerald-400/30"
          />
          <input
            type="text"
            value={kinds}
            onChange={(event) => setKinds(event.target.value)}
            placeholder="Tipo: fail, reaccion, gag"
            aria-label="Clases de momento que acepta"
            className="min-w-0 flex-1 rounded-xl border border-white/10 bg-white/[0.03] px-4 py-2.5 text-sm text-zinc-100 placeholder:text-zinc-600 focus:border-emerald-400/50 focus:outline-none focus:ring-1 focus:ring-emerald-400/30"
          />
          <input
            type="text"
            value={niche}
            onChange={(event) => setNiche(event.target.value)}
            placeholder="Nicho"
            aria-label="Nicho que acepta"
            className="w-full rounded-xl border border-white/10 bg-white/[0.03] px-4 py-2.5 text-sm text-zinc-100 placeholder:text-zinc-600 focus:border-emerald-400/50 focus:outline-none focus:ring-1 focus:ring-emerald-400/30 sm:w-36"
          />
          <input
            type="number"
            min={0}
            max={100}
            value={minScore}
            onChange={(event) => setMinScore(event.target.value)}
            placeholder="Nota mín."
            aria-label="Nota mínima"
            title="Este canal puede ser más exigente que el sistema"
            className="w-full rounded-xl border border-white/10 bg-white/[0.03] px-4 py-2.5 text-sm text-zinc-100 placeholder:text-zinc-600 focus:border-emerald-400/50 focus:outline-none focus:ring-1 focus:ring-emerald-400/30 sm:w-28"
          />
          <button
            type="submit"
            disabled={busy || name.trim().length === 0}
            className="rounded-xl border border-white/10 px-5 py-2.5 text-sm text-zinc-200 transition hover:border-white/25 hover:text-white disabled:cursor-not-allowed disabled:opacity-40"
          >
            {busy ? "Añadiendo…" : "Añadir"}
          </button>
        </div>
      </form>

      {(formError ?? error) && (
        <p role="alert" className="mt-3 text-sm text-rose-400">
          {formError ?? error}
        </p>
      )}

      {channels && channels.length === 0 && (
        <p className="mt-3 rounded-xl border border-dashed border-white/10 px-4 py-6 text-center text-sm text-zinc-500">
          Ningún canal de publicación todavía. Sin ellos, los clips se quedan sin repartir.
        </p>
      )}

      {channels && channels.length > 0 && (
        <ul className="mt-3 space-y-2">
          {channels.map((channel) => {
            const assigned = pending.filter((clip) => clip.channel_id === channel.id);
            return (
              <li
                key={channel.id}
                className="flex flex-wrap items-center gap-3 rounded-xl border border-white/10 bg-white/[0.03] p-3"
              >
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm text-zinc-100">
                    {channel.name}
                    {!channel.enabled && (
                      <span className="ml-2 text-xs text-zinc-600">(pausado)</span>
                    )}
                    <span className="ml-2 text-xs text-emerald-400/80">
                      {assigned.length} {assigned.length === 1 ? "clip" : "clips"} en espera
                    </span>
                  </p>
                  <p className="mt-0.5 truncate text-xs text-zinc-500">
                    {/* Los temas cuentan como filtro: sin pintarlos, un canal
                        que solo filtra por tema decia "acepta cualquier clip",
                        que es justo lo contrario de lo que hace. */}
                    {[
                      channel.people.length > 0 ? channel.people.join(", ") : null,
                      channel.topics.length > 0 ? channel.topics.join(", ") : null,
                      channel.kinds.length > 0 ? channel.kinds.join(" · ") : null,
                      channel.niche,
                      channel.min_score > 0 ? `nota ≥ ${channel.min_score}` : null,
                    ]
                      .filter(Boolean)
                      .join("  ·  ") || "Acepta cualquier clip"}
                  </p>
                </div>

                {/* El cierre: el nombre que sale al final de sus clips. Se
                    escribe aquí y se fabrica aparte, porque generarlo
                    cuesta una recodificación. */}
                <input
                  type="text"
                  value={handles[channel.id] ?? channel.outro_handle ?? ""}
                  onChange={(event) =>
                    setHandles((current) => ({
                      ...current,
                      [channel.id]: event.target.value,
                    }))
                  }
                  onBlur={(event) => {
                    const value = event.target.value.trim();
                    if (value === (channel.outro_handle ?? "")) return;
                    void act(() =>
                      updatePublishChannel(channel.id, { outro_handle: value }),
                    );
                  }}
                  placeholder="@nombre del cierre"
                  aria-label={`Nombre en el cierre de ${channel.name}`}
                  title="El nombre que sale al final de cada clip de este canal"
                  className="w-40 shrink-0 rounded-lg border border-white/10 bg-white/[0.03] px-3 py-1.5 text-xs text-zinc-300 placeholder:text-zinc-600 focus:border-emerald-400/50 focus:outline-none"
                />
                <button
                  type="button"
                  disabled={buildingId !== null}
                  onClick={() => {
                    setBuildingId(channel.id);
                    void act(() => buildChannelOutro(channel.id)).finally(() =>
                      setBuildingId(null),
                    );
                  }}
                  title="Fabrica el vídeo de cierre con este nombre"
                  className={`shrink-0 rounded-lg border px-3 py-1.5 text-xs transition disabled:cursor-not-allowed disabled:opacity-40 ${
                    channel.has_outro
                      ? "border-emerald-400/30 text-emerald-400/90 hover:border-emerald-400/60"
                      : "border-white/10 text-zinc-400 hover:border-white/25 hover:text-zinc-200"
                  }`}
                >
                  {buildingId === channel.id
                    ? "Generando…"
                    : channel.has_outro
                      ? "Cierre ✓"
                      : "Generar cierre"}
                </button>

                {/* Un enlace a ninguna parte seria peor que no tenerlo: */}
                {channel.url ? (
                  <a
                    href={channel.url}
                    target="_blank"
                    rel="noreferrer"
                    className="shrink-0 rounded-lg border border-white/10 px-3 py-1.5 text-xs text-zinc-300 transition hover:border-white/20 hover:text-zinc-100"
                  >
                    Abrir
                  </a>
                ) : (
                  <span className="shrink-0 rounded-lg border border-dashed border-white/10 px-3 py-1.5 text-xs text-zinc-600">
                    Sin URL
                  </span>
                )}
                <button
                  type="button"
                  onClick={() =>
                    void act(() =>
                      updatePublishChannel(channel.id, { enabled: !channel.enabled }),
                    )
                  }
                  className="shrink-0 rounded-lg border border-white/10 px-3 py-1.5 text-xs text-zinc-300 transition hover:border-white/20 hover:text-zinc-100"
                >
                  {channel.enabled ? "Pausar" : "Reanudar"}
                </button>
                <button
                  type="button"
                  onClick={() => void act(() => deletePublishChannel(channel.id))}
                  className="shrink-0 rounded-lg border border-white/10 px-3 py-1.5 text-xs text-zinc-500 transition hover:border-rose-500/40 hover:text-rose-400"
                >
                  Quitar
                </button>
              </li>
            );
          })}
        </ul>
      )}

      {/* Los huérfanos son la señal más útil de esta pantalla: dicen qué línea
          editorial falta o qué clip hay que colocar a mano. */}
      {orphans.length > 0 && (
        <p className="mt-3 text-xs text-amber-400/80">
          {orphans.length} {orphans.length === 1 ? "clip no encaja" : "clips no encajan"} en
          ningún canal. Ajusta los filtros o repártelos a mano.
        </p>
      )}
    </section>
  );
}
