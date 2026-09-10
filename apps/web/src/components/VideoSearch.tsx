"use client";

import { useState, type FormEvent } from "react";

import { createBatch, searchVideos } from "@/lib/api";
import type { VideoResult } from "@/lib/types";

interface Props {
  /** Se invoca tras encolar para que la lista de proyectos se entere ya. */
  onQueued: () => void;
}

function formatDuration(seconds: number | null): string {
  if (!seconds) return "—";
  const total = Math.round(seconds);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const rest = total % 60;
  const pad = (value: number) => String(value).padStart(2, "0");
  return hours > 0 ? `${hours}:${pad(minutes)}:${pad(rest)}` : `${minutes}:${pad(rest)}`;
}

function formatViews(views: number | null): string {
  if (views === null) return "—";
  if (views >= 1_000_000) return `${(views / 1_000_000).toFixed(1)}M`;
  if (views >= 1_000) return `${Math.round(views / 1_000)}K`;
  return String(views);
}

/**
 * Buscador de vídeos dentro de la aplicación.
 *
 * Antes había que ir a YouTube, buscar, copiar la URL y volver. Y de uno en
 * uno. Aquí se busca, se marcan varios y entran todos en la cola.
 *
 * Los resultados traen duración y vistas porque son los dos datos con los que
 * se decide, y decidir **antes** de descargar es el objetivo: bajar 400 MB
 * para ver que el vídeo duraba tres horas es el gasto más tonto del pipeline.
 */
export function VideoSearch({ onQueued }: Props) {
  const [query, setQuery] = useState("");
  const [keywords, setKeywords] = useState("");
  const [results, setResults] = useState<VideoResult[] | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [searching, setSearching] = useState(false);
  const [queueing, setQueueing] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (searching || query.trim().length === 0) return;

    setSearching(true);
    setError(null);
    setMessage(null);
    setSelected(new Set());
    try {
      setResults(await searchVideos(query.trim()));
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : "No se ha podido buscar");
      setResults(null);
    } finally {
      setSearching(false);
    }
  }

  function toggle(url: string) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(url)) next.delete(url);
      else next.add(url);
      return next;
    });
  }

  async function queue() {
    if (selected.size === 0) return;

    setQueueing(true);
    setError(null);
    try {
      const result = await createBatch([...selected], keywords);
      const parts = [`${result.queued.length} en cola`];
      if (result.duplicated.length > 0) parts.push(`${result.duplicated.length} ya estaban`);
      const failed = Object.keys(result.rejected).length;
      if (failed > 0) parts.push(`${failed} rechazadas`);

      setMessage(parts.join(" · "));
      setSelected(new Set());
      // Los que acaban de entrar ya no se pueden volver a encolar.
      setResults((current) =>
        current === null
          ? null
          : current.map((video) =>
              result.queued.length > 0 && selected.has(video.url)
                ? { ...video, already_queued: true }
                : video,
            ),
      );
      onQueued();
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : "No se han podido encolar");
    } finally {
      setQueueing(false);
    }
  }

  return (
    <section aria-label="Buscar vídeos" className="mt-10">
      <h2 className="text-sm font-medium text-zinc-400">Buscar en YouTube</h2>

      <form onSubmit={handleSearch} className="mt-3 flex flex-col gap-3 sm:flex-row">
        <input
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="De qué quieres clips (kai cenat, comedia, retos…)"
          aria-label="Qué buscar en YouTube"
          className="min-w-0 flex-1 rounded-xl border border-white/10 bg-white/[0.03] px-4 py-3 text-sm text-zinc-100 placeholder:text-zinc-600 focus:border-emerald-400/50 focus:outline-none focus:ring-1 focus:ring-emerald-400/30"
        />
        <button
          type="submit"
          disabled={searching || query.trim().length === 0}
          className="rounded-xl border border-white/10 px-5 py-3 text-sm text-zinc-200 transition hover:border-white/25 hover:text-white disabled:cursor-not-allowed disabled:opacity-40"
        >
          {searching ? "Buscando…" : "Buscar"}
        </button>
      </form>

      {error && (
        <p role="alert" className="mt-3 text-sm text-rose-400">
          {error}
        </p>
      )}
      {message && <p className="mt-3 text-sm text-emerald-400/80">{message}</p>}

      {results !== null && results.length === 0 && (
        <p className="mt-3 rounded-xl border border-dashed border-white/10 px-4 py-6 text-center text-sm text-zinc-500">
          Sin resultados para «{query}».
        </p>
      )}

      {results !== null && results.length > 0 && (
        <>
          <ul className="mt-3 space-y-2">
            {results.map((video) => {
              const checked = selected.has(video.url);
              return (
                <li key={video.video_id}>
                  <label
                    className={`flex cursor-pointer items-center gap-3 rounded-xl border p-2.5 transition ${
                      checked
                        ? "border-emerald-500/40 bg-emerald-500/[0.06]"
                        : "border-white/10 bg-white/[0.03] hover:border-white/20"
                    } ${video.already_queued ? "opacity-50" : ""}`}
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      disabled={video.already_queued}
                      onChange={() => toggle(video.url)}
                      className="h-4 w-4 shrink-0 accent-emerald-500"
                    />

                    <div className="h-12 w-20 shrink-0 overflow-hidden rounded-lg bg-black/40">
                      {video.thumbnail && (
                        // Miniatura remota de YouTube: <img> evita configurar dominios en next/image.
                        // eslint-disable-next-line @next/next/no-img-element
                        <img
                          src={video.thumbnail}
                          alt=""
                          className="h-full w-full object-cover"
                          loading="lazy"
                        />
                      )}
                    </div>

                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm text-zinc-100">{video.title}</p>
                      <p className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-zinc-500">
                        <span className="truncate">{video.channel ?? "—"}</span>
                        <span aria-hidden="true">·</span>
                        <span className="tabular-nums">{formatDuration(video.duration)}</span>
                        <span aria-hidden="true">·</span>
                        <span className="tabular-nums">{formatViews(video.view_count)} vistas</span>
                        {video.already_queued && (
                          <span className="text-amber-400/80">· ya está en tus proyectos</span>
                        )}
                      </p>
                    </div>
                  </label>
                </li>
              );
            })}
          </ul>

          <div className="mt-3 flex flex-col gap-3 sm:flex-row sm:items-center">
            <input
              type="text"
              value={keywords}
              onChange={(event) => setKeywords(event.target.value)}
              placeholder="Opcional: palabras clave para todos los de la tanda"
              aria-label="Palabras clave de la tanda"
              className="min-w-0 flex-1 rounded-xl border border-white/10 bg-white/[0.03] px-4 py-2.5 text-sm text-zinc-100 placeholder:text-zinc-600 focus:border-emerald-400/50 focus:outline-none focus:ring-1 focus:ring-emerald-400/30"
            />
            <button
              type="button"
              onClick={() => void queue()}
              disabled={queueing || selected.size === 0}
              className="rounded-xl bg-emerald-500 px-5 py-2.5 text-sm font-medium text-zinc-950 transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:bg-zinc-800 disabled:text-zinc-500"
            >
              {queueing
                ? "Encolando…"
                : `Generar clips de ${selected.size} ${selected.size === 1 ? "vídeo" : "vídeos"}`}
            </button>
          </div>
        </>
      )}
    </section>
  );
}
