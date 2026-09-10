"use client";

import { useState, type FormEvent } from "react";

import { createProject } from "@/lib/api";

interface Props {
  /** Se invoca tras crear un proyecto para refrescar la lista sin esperar al polling. */
  onCreated: () => void;
}

export function NewProjectForm({ onCreated }: Props) {
  const [url, setUrl] = useState("");
  // Lo único que el sistema no puede deducir mirando el vídeo: quién sale y
  // cómo se le busca. El título de YouTube casi nunca nombra a los
  // streamers que aparecen, y es ese nombre el que se busca en Shorts.
  const [keywords, setKeywords] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting) return;

    setSubmitting(true);
    setError(null);
    try {
      await createProject(url.trim(), keywords);
      setUrl("");
      setKeywords("");
      onCreated();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "No se ha podido crear el proyecto");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} noValidate>
      <div className="flex flex-col gap-3 sm:flex-row">
        <input
          type="url"
          value={url}
          onChange={(event) => setUrl(event.target.value)}
          placeholder="Pega una URL de YouTube"
          aria-label="URL de YouTube"
          aria-invalid={error !== null}
          className="min-w-0 flex-1 rounded-xl border border-white/10 bg-white/[0.03] px-4 py-3 text-sm text-zinc-100 placeholder:text-zinc-600 focus:border-emerald-400/50 focus:outline-none focus:ring-1 focus:ring-emerald-400/30"
        />
        <button
          type="submit"
          disabled={submitting || url.trim().length === 0}
          className="rounded-xl bg-emerald-500 px-5 py-3 text-sm font-medium text-zinc-950 transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:bg-zinc-800 disabled:text-zinc-500"
        >
          {submitting ? "Creando…" : "Generar clips"}
        </button>
      </div>

      <input
        type="text"
        value={keywords}
        onChange={(event) => setKeywords(event.target.value)}
        placeholder="Opcional: de qué va y quién sale (Kai Cenat, Speed, Among Us)"
        aria-label="Palabras clave del vídeo"
        className="mt-3 w-full rounded-xl border border-white/10 bg-white/[0.03] px-4 py-3 text-sm text-zinc-100 placeholder:text-zinc-600 focus:border-emerald-400/50 focus:outline-none focus:ring-1 focus:ring-emerald-400/30"
      />
      <p className="mt-2 text-xs text-zinc-500">
        Se usan para titular los clips con los nombres por los que la gente busca.
        Sepáralas por comas.
      </p>

      {error && (
        <p role="alert" className="mt-3 text-sm text-rose-400">
          {error}
        </p>
      )}
    </form>
  );
}
