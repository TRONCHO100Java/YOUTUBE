"use client";

import { useCallback, useState, type FormEvent } from "react";

import { usePolling } from "@/hooks/usePolling";
import {
  addChannel,
  checkChannel,
  deleteChannel,
  listChannels,
  updateChannel,
} from "@/lib/api";
import { POLL_INTERVAL_MS } from "@/lib/config";
import type { WatchedChannel } from "@/lib/types";

function formatWhen(iso: string | null): string {
  if (!iso) return "nunca";
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (minutes < 1) return "ahora mismo";
  if (minutes < 60) return `hace ${minutes} min`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `hace ${hours} h`;
  return `hace ${Math.round(hours / 24)} d`;
}

/**
 * Canales vigilados: los vídeos que llegan solos.
 *
 * Es lo que separa una herramienta que conduces de algo que corre solo. Das de
 * alta un canal y sus vídeos nuevos se procesan sin que nadie pegue una URL.
 *
 * Al dar de alta un canal se empieza a mirar **desde ahora**, no desde su
 * historial: vigilar un canal es querer lo que publique a partir de este
 * momento, y lo contrario encolaría sus quince últimos vídeos de golpe.
 */
export function ChannelsPanel() {
  const fetcher = useCallback(() => listChannels(), []);
  const { data: channels, error, refresh } = usePolling<WatchedChannel[]>(
    fetcher,
    POLL_INTERVAL_MS,
  );

  const [channel, setChannel] = useState("");
  const [keywords, setKeywords] = useState("");
  const [maxDuration, setMaxDuration] = useState("");
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  async function handleAdd(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || channel.trim().length === 0) return;

    setBusy(true);
    setFormError(null);
    try {
      await addChannel({
        channel: channel.trim(),
        keywords,
        maxDuration: maxDuration ? Number(maxDuration) * 60 : undefined,
      });
      setChannel("");
      setKeywords("");
      setMaxDuration("");
      refresh();
    } catch (cause: unknown) {
      setFormError(cause instanceof Error ? cause.message : "No se ha podido añadir");
    } finally {
      setBusy(false);
    }
  }

  async function act(action: () => Promise<unknown>) {
    setFormError(null);
    try {
      await action();
      refresh();
    } catch (cause: unknown) {
      setFormError(cause instanceof Error ? cause.message : "No se ha podido");
    }
  }

  return (
    <section aria-label="Canales vigilados" className="mt-10">
      <h2 className="text-sm font-medium text-zinc-400">Canales vigilados</h2>
      <p className="mt-1 text-xs text-zinc-500">
        Sus vídeos nuevos entran solos en la cola. Se empieza a mirar desde ahora, no desde
        su historial.
      </p>

      <form onSubmit={handleAdd} className="mt-3 flex flex-col gap-3 sm:flex-row">
        <input
          type="text"
          value={channel}
          onChange={(event) => setChannel(event.target.value)}
          placeholder="@KaiCenat, la URL del canal o la de uno de sus vídeos"
          aria-label="Canal a vigilar"
          className="min-w-0 flex-1 rounded-xl border border-white/10 bg-white/[0.03] px-4 py-2.5 text-sm text-zinc-100 placeholder:text-zinc-600 focus:border-emerald-400/50 focus:outline-none focus:ring-1 focus:ring-emerald-400/30"
        />
        <input
          type="number"
          min={1}
          value={maxDuration}
          onChange={(event) => setMaxDuration(event.target.value)}
          placeholder="Máx. min"
          aria-label="Duración máxima en minutos"
          title="Ignora los vídeos más largos que esto. Sin valor, no filtra por duración"
          className="w-full rounded-xl border border-white/10 bg-white/[0.03] px-4 py-2.5 text-sm text-zinc-100 placeholder:text-zinc-600 focus:border-emerald-400/50 focus:outline-none focus:ring-1 focus:ring-emerald-400/30 sm:w-28"
        />
        <button
          type="submit"
          disabled={busy || channel.trim().length === 0}
          className="rounded-xl border border-white/10 px-5 py-2.5 text-sm text-zinc-200 transition hover:border-white/25 hover:text-white disabled:cursor-not-allowed disabled:opacity-40"
        >
          {busy ? "Añadiendo…" : "Vigilar"}
        </button>
      </form>

      <input
        type="text"
        value={keywords}
        onChange={(event) => setKeywords(event.target.value)}
        placeholder="Opcional: palabras clave para los clips de este canal"
        aria-label="Palabras clave del canal"
        className="mt-3 w-full rounded-xl border border-white/10 bg-white/[0.03] px-4 py-2.5 text-sm text-zinc-100 placeholder:text-zinc-600 focus:border-emerald-400/50 focus:outline-none focus:ring-1 focus:ring-emerald-400/30"
      />

      {(formError ?? error) && (
        <p role="alert" className="mt-3 text-sm text-rose-400">
          {formError ?? error}
        </p>
      )}

      {channels && channels.length === 0 && (
        <p className="mt-3 rounded-xl border border-dashed border-white/10 px-4 py-6 text-center text-sm text-zinc-500">
          Ningún canal vigilado todavía.
        </p>
      )}

      {channels && channels.length > 0 && (
        <ul className="mt-3 space-y-2">
          {channels.map((watched) => (
            <li
              key={watched.id}
              className="flex flex-wrap items-center gap-3 rounded-xl border border-white/10 bg-white/[0.03] p-3"
            >
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm text-zinc-100">
                  {watched.title}
                  {!watched.enabled && (
                    <span className="ml-2 text-xs text-zinc-600">(pausado)</span>
                  )}
                </p>
                <p className="mt-0.5 text-xs text-zinc-500">
                  Revisado {formatWhen(watched.last_checked_at)} · {watched.projects_created}{" "}
                  {watched.projects_created === 1 ? "proyecto" : "proyectos"}
                  {watched.max_duration ? ` · máx. ${Math.round(watched.max_duration / 60)} min` : ""}
                </p>
                {watched.last_error && (
                  <p className="mt-1 truncate text-xs text-rose-400/80" title={watched.last_error}>
                    {watched.last_error}
                  </p>
                )}
              </div>

              <button
                type="button"
                onClick={() => void act(() => checkChannel(watched.id))}
                title="Revisar este canal ahora, sin esperar al temporizador"
                className="shrink-0 rounded-lg border border-white/10 px-3 py-1.5 text-xs text-zinc-300 transition hover:border-white/20 hover:text-zinc-100"
              >
                Revisar
              </button>
              <button
                type="button"
                onClick={() =>
                  void act(() => updateChannel(watched.id, { enabled: !watched.enabled }))
                }
                className="shrink-0 rounded-lg border border-white/10 px-3 py-1.5 text-xs text-zinc-300 transition hover:border-white/20 hover:text-zinc-100"
              >
                {watched.enabled ? "Pausar" : "Reanudar"}
              </button>
              <button
                type="button"
                onClick={() => void act(() => deleteChannel(watched.id))}
                className="shrink-0 rounded-lg border border-white/10 px-3 py-1.5 text-xs text-zinc-500 transition hover:border-rose-500/40 hover:text-rose-400"
              >
                Quitar
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
